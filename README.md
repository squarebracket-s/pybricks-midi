# pybricks-midi
MIDI Player intended for the Mindstorms Prime/Inventor Hub on Pybricks firmware.  
Files have to be parsed on a host machine first, then transferred to the hub.  
  
## Setup   
Upload `hub/music_player.py` to your Pybricks Hub.  
This can be done using the [web interface](https://code.pybricks.com/).  
Recommended Python version for the host program is 3.14.  
To install the dependencies:  
`pip install -r requirements.txt`  
**Note: `main.py` can only connect to the hub while it is idle.**