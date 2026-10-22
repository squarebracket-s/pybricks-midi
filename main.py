# Main
import asyncio
import time
import argparse
from contextlib import suppress
from bleak import BleakScanner, BleakClient
from bleak.exc import BleakGATTProtocolError

# Midi parsing
from mido import MidiFile, tick2second, bpm2tempo

def note_to_freq(a):
    return (440 / 32) * (2 ** ((a - 9) / 12))

class MidiNotes:
    def __init__(self, filepath: str, start_time: int=0, tempo: int=bpm2tempo(95), note_limit: int=0, normalize_volume: bool=True):
        # NOTE: clip=True clamps values 0-127
        self.midi_file = MidiFile(filepath, clip=True)

        self.notes = []
        volume_by_channel = {}
        cur_time = 0
        for msg in self.midi_file.merged_track:
            cur_time += tick2second(msg.time, self.midi_file.ticks_per_beat, tempo)
            if msg.type == "note_on" and cur_time > start_time:
                notevol = 128 if msg.channel not in volume_by_channel.keys() else volume_by_channel[msg.channel]
                notevol = int(round(notevol*(msg.velocity/127),2)*100)
                notevol = max(256,notevol)
                if msg.velocity > 0:
                    self.notes.append([msg.note,notevol,round(cur_time-start_time,2)])
            if msg.type == "set_tempo":
                tempo = msg.tempo
            if msg.is_cc(7):
                volume_by_channel[msg.channel] = msg.value
            if msg.type == "reset":
                tempo = bpm2tempo(95)
                volume_by_channel[msg.channel] = 128

        self.notes.sort(key=lambda note: note[-1]) # Sort notes by real time (not delta!)
        if note_limit:
            self.notes = self.notes[:note_limit]

        # Normalize volume =========
        if normalize_volume:
            max_vol = max(note[1] for note in self.notes)
            voldiff = 12800-max_vol
            for note in self.notes: note[1] += voldiff

        # Metadata =========
        self.freq_high = 0
        self.freq_low = 24000
        for note in self.notes:
            nfreq = note_to_freq(note[0])
            if self.freq_high<nfreq:
                self.freq_high=nfreq
            elif self.freq_low>nfreq:
                self.freq_low=nfreq

            note[-1]=int(note[-1]*100) # time: float -> integer (will be divided by 100 on local machine)
        
        self.freq_high = self.freq_high-self.freq_low
        
        self.note_chunk_size = [
            2, # MIDI Note (Max 127, Hex Max 256)
            4, # MIDI Volume * 100 (Max 12800, Hex Max 65536)
            len(hex(self.notes[-1][-1]))-2 # Note time * 100 (Dynamic)
        ]
        

EOF = b'\r\n'
MAX_CHAR_SIZE = 63
rx_buffer = bytearray()

def _pybricks_uuid(short: int) -> str:
    return f"c5f5{short:04x}-8280-46da-89f4-6d8051e4aeef"
PYBRICKS_COMMAND_EVENT_UUID = _pybricks_uuid(0x0002)

parser = argparse.ArgumentParser()
parser.add_argument("filename", help="MIDI file to upload")
parser.add_argument("-n", "--name", help="hub name", default="Pybricks Hub")
parser.add_argument("-v", "--volume", help="hub volume 0-100 (default: 50)", type=int, default=50)
parser.add_argument("-q", "--quiet", help="(bool) suppress asyncio.CancelledError (disable to show hub exception traceback messages)", type=bool)
parser.add_argument("-nl", "--note-limit", help="midi note limit (default: 15000)", type=int, default=15000)
cmd_args = parser.parse_args()

async def main():
    main_task = asyncio.current_task()

    def handle_disconnect(_):
        print("Hub was disconnected.")

        # If the hub disconnects before this program is done,
        # cancel this program so it doesn't get stuck waiting
        # forever.
        if not main_task.done():
            main_task.cancel()

    def tobytelist(*args):
        return bytes(",".join(map(str,[*args])), "utf-8")

    # Do a Bluetooth scan to find the hub.
    device = await BleakScanner.find_device_by_name(cmd_args.name)

    if device is None:
        print(f"Could not find hub with name: {cmd_args.name}")
        return

    # Connect to the hub.
    async with BleakClient(device, handle_disconnect) as client:

        # Shorthand for sending some data to the hub.
        async def send(data, endline=True, response=True):
            print("-> ",data,len(data))
            try:
                await client.write_gatt_char(
                    PYBRICKS_COMMAND_EVENT_UUID,
                    b"\x06" + data.replace(b" ",b"") + (b"\\" * int(endline)),  # prepend "write stdin" command (0x06)
                    response=response,
                )
                return True
            except BleakGATTProtocolError:
                print("Failed write!")
                return False

        # Subscribe to notifications from the hub.
        async def handle_rx(_, data: bytearray):
            if data[0] == 0x01:  # "write stdout" event (0x01)
                global rx_buffer
                payload = data[1:]
                rx_buffer.extend(payload)
                if EOF in rx_buffer:
                    received = rx_buffer.split(EOF)[0]
                    try:
                        rx_buffer = rx_buffer.split(EOF)[1]
                    except IndexError:
                        rx_buffer = bytearray()
                    print("<- ", received)

                    if received.strip() == b"M":
                        # meta,[notelen],[notefreq_low],[notefreq_high],[maxtime]
                        # TODO: Fix time_size inconsistency (currently has to be given by metadata message)
                        metadata = b"M"+tobytelist(len(MUSIC.notes), round(MUSIC.freq_low,2), round(MUSIC.freq_high,2), round(MUSIC.notes[-1][1],2), MUSIC.note_chunk_size[2], max(0, min(100,cmd_args.volume)))
                        await send(metadata)
                    elif received.startswith(b"G"): # G => getchunk
                        t_start = time.time()
                        # <- !getchunk,0,1024
                        # -> note,volume,time*100
                        print("[G] Parse getchunk request")
                        data = list(map(int,received.decode("utf-8").strip().split("::")[-1][1:].split(",")))
                        assert data[1] <= len(MUSIC.notes)

                        # Split notes into chunks for faster transfer
                        print("[G] Create chunks")
                        buf = b""
                        for i in range(data[0],data[1]):
                            note = MUSIC.notes[i]
                            buf += b"".join([bytes(format(val,f"0{MUSIC.note_chunk_size[idx]}x"),"utf-8") for idx,val in enumerate(note)])

                        print("[G] Send chunks")
                        await send(b"N")
                        for n in range(0,len(buf),MAX_CHAR_SIZE):
                            chunk = buf[n:n+MAX_CHAR_SIZE]
                            if not (await send(chunk,endline=False)):
                                break
                        await send(b"E\n")
                        print(f"[G] Took {time.time()-t_start}s")

        await client.start_notify(PYBRICKS_COMMAND_EVENT_UUID, handle_rx)

        print("Connected to hub.")
        MUSIC = MidiNotes(cmd_args.filename, note_limit=cmd_args.note_limit)
        print("Start the program on the hub with the button.")
        while True:
            await asyncio.sleep(10)


if __name__ == "__main__":
    if cmd_args.quiet:
        with suppress(asyncio.CancelledError):
            asyncio.run(main())
    else:
        asyncio.run(main())
