from pytube import YouTube # for audio extraction
import yt_dlp

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