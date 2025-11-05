import yt_dlp # for audio extraction
import ffmpeg
from pydub import AudioSegment

import requests # for image extraction
from PIL import Image
from io import BytesIO

from colorthief import ColorThief #For image colour extraction
import matplotlib.pyplot as plt

mp3URL = str(input("Enter Audio URL"))
imgurl = str(input("Enter Image URL"))

#------------------------------------------- EXTRACTING AUDIO
#'''
ydl_opts = {
    'format': 'mp3/bestaudio/best',
    'postprocessors': [{  # Extract audio using ffmpeg
        'key': 'FFmpegExtractAudio',
        'preferredcodec': 'mp3',
    }]
}

with yt_dlp.YoutubeDL(ydl_opts) as ydl:
    error_code = ydl.download(mp3URL)
#'''
#---------------------------------------- TRIMMING AUDIO
#'''
def mmss_to_milliseconds(time_str):
    m, s = map(int, time_str.split(':'))
    return ((m * 60) + s) * 1000
 
# Load audio file
song = AudioSegment.from_file("travis.mp3", format="mp3")
 
# Take input from user
start_time = input("Enter start time (MM:SS): ")
end_time = input("Enter end time (MM:SS): ")
 
# Convert to milliseconds
start_ms = mmss_to_milliseconds(start_time)
end_ms = mmss_to_milliseconds(end_time)

# Slice the audio
clip = song[start_ms:end_ms]
 
# Export new audio clip
clip.export("Mid.mp3", format="mp3")
print("New Audio file is created and saved as Mid.mp3")


#'''
#---------------------------------------- EXTRACTING PNG
#'''
if __name__ == '__main__':
    
    response = requests.get(imgurl)
    print(response)
    if response.status_code == 200:
        img = Image.open(BytesIO(response.content))
        img.save('C:/Users/aliba/Downloads/MacbookVisuals/MV-AE-Project-Automation/image.png')
    else:
        print("BAD IMAGE LINK")
#'''
#--------------------------------------- EXTRACTING COLORS FROM PNG
#'''
xremiximg = ColorThief("image.png") # setup image for extraction

palette = xremiximg.get_palette(color_count=4) # getting the 4 most dominant colours

with open('output.txt', 'w'): # removes previous 4 colours
    pass

for r,g,b in palette: 
    hexvalue = '#' + format(r,'02x') + format(g,'02x') + format(b,'02x')# convert rgb values into hex
    with open('output.txt', 'a') as file: # append values into output file
        file.write(hexvalue + '\n')
#'''
#-------------------------------------- Taking in lyrics