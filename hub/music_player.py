from pybricks.hubs import InventorHub
from pybricks.tools import multitask, wait, run_task, StopWatch, read_input_byte

from usys import stdin

hub = InventorHub()
MAX_VOL = 50

SEP = const(',')
EOF = const('\\')
NOTE_PART_SIZE = [2, 4, None]

timer = StopWatch()
timer.pause()
timer.reset()
time=0

played_music = [0,0,0,0,0]
def note_to_freq(note):
    return (440 / 32) * (2 ** ((note - 9) / 12))

# NOTE: Async method to read buffer
# https://github.com/pybricks/pybricks-micropython/pull/177

def set_progress_bar(part,full):
    pct = (part/full)*100
    for row in range(5):
        for col in range(5):
            # 4% per pixel
            px_pct = (4 * col) + (20 * row)
            hub.display.pixel(row,col,max(0,min(1,(pct-px_pct)))*100)

async def recv():
    print("M")
    nc = 0
    buffer = ''
    while True:
        char = read_input_byte(chr=True)
        if char == EOF:
            if buffer.startswith(b"EG"):
                print("EndGrace")
                break
            elif buffer.startswith(b"M"):
                # TODO: Also compress metadata message?
                global max_time, hf, lf
                notelen,lf,hf,max_time,time_size,MAX_VOL = tuple(map(float,str(buffer,"utf-8")[1:].split(SEP)))
                notelen = int(notelen)
                NOTE_PART_SIZE[2] = int(time_size)
                max_time = max_time*100
                notes = [None]*(notelen*3) # Preallocate list to prevent any memory allocation issues from ocurring
                print(f"G0,{notelen}")
            elif buffer.startswith(b"N"):
                print("bufreader start",NOTE_PART_SIZE[2])
                while True:
                    buf = stdin.buffer.read(NOTE_PART_SIZE[nc%3])
                    if buf == b"E\n": break
                    notes[nc] = int(buf,16)
                    nc+=1
                    set_progress_bar(nc,notelen*3)
                    if any(hub.buttons.pressed()): break
                print("bufreader end")

                # Snap max note amount to lowest multiple of 3 to prevent playing data not fully loaded.
                nc -= nc % 3

                hub.display.off()
                while not any(hub.buttons.pressed()):
                    await wait(10)
                await wait(5000)

                timer.resume()
                idx = 0
                while True:
                    time = timer.time()/10
                    if (time<max_time) and idx < nc:
                        timer.resume()
                        if notes[idx+2]<time:
                            dist = abs(notes[idx+2]-time)
                            nfreq = note_to_freq(notes[idx])
                            pm_idx = round(((nfreq-lf)/hf)*4)
                            vol_div = ((notes[idx+1]/100) / 128)
                            played_music[pm_idx] = played_music[pm_idx]+(2*vol_div)
                            hub.speaker.volume(vol_div * MAX_VOL)
                            await hub.speaker.beep(nfreq,6)
                            idx += 3
                        else:
                            await wait(abs((notes[idx+2]*10)-(timer.time())))
                    else:
                        hub.display.off()
                        hub.display.pixel(2,2,brightness=100)
            buffer = ""
        elif char is not None:
            buffer += char

async def display():
    global max_time, time
    while True:
        if (time<max_time):
            hub.display.off()
            for x in range(5):
                if played_music[x]>5: played_music[x]=5
                for y in range(round(played_music[x])):
                    hub.display.pixel(4-y,x,brightness=100)
                played_music[x] = played_music[x]-0.5
                if played_music[x]<1/9:
                    played_music[x]=1/9
        await wait(1000*(1/60))

async def main():
    await multitask(recv(),display(),race=False)

run_task(main())
