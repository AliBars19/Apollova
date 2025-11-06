import os
import json

import yt_dlp # for audio extraction
import ffmpeg
from pydub import AudioSegment

import requests # for image extraction
from PIL import Image
from io import BytesIO

from colorthief import ColorThief #For image colour extraction
import matplotlib.pyplot as plt

#-----------------------creating job folders

job_id = 1
job_folder = f"jobs/job_{job_id:03}"
os.makedirs(job_folder, exist_ok=True)
print("created", job_folder)

#-----------------------
mp3URL = str(input("Enter Audio URL"))
#------------------------------------------- EXTRACTING AUDIO

def download_audio(url,job_folder):
    output_path = os.path.join(job_folder, 'audio_source.%(ext)s')

    ydl_opts = {
        'format': 'bestaudio/best',
        'outtmpl': output_path,
        'postprocessors': [{  # Extract audio using ffmpeg
            'key': 'FFmpegExtractAudio',
            'preferredcodec': 'mp3',
        }]
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        ydl.download([url])

    mp3_path = os.path.join(job_folder, 'audio_source.mp3')
    return mp3_path # return path of mp3

#---------------------------------------- TRIMMING AUDIO

def mmss_to_millisecondsaudio(time_str):
    m, s = map(int, time_str.split(':'))
    return ((m * 60) + s) * 1000
 
def trimming_audio(job_folder,start_time, end_time):

    audio_import = os.path.join(job_folder,'audio_source.mp3')# Load audio file
    song = AudioSegment.from_file(audio_import, format="mp3")
    
    start_ms = mmss_to_millisecondsaudio(start_time)# Convert to milliseconds
    end_ms = mmss_to_millisecondsaudio(end_time)

    if start_ms < end_ms:
        clip = song[start_ms:end_ms]# Slice the audio
    else:
        print("start time cannot be bigger than end time")
        return None
    
    export_path = os.path.join(job_folder, "audio_trimmed.wav")# Export new audio clip
    clip.export(export_path, format="wav")
    print("New Audio file is created and saved")
    return export_path


#---------------------------------------- DOWNLOADING PNG

def image_download(job_folder,url):
    image_save_path = os.path.join(job_folder,'cover.png')
    response = requests.get(url)
    print(response)
    if response.status_code == 200:
        img = Image.open(BytesIO(response.content))
        img.save(image_save_path)
    else:
        print("BAD IMAGE LINK")

    return image_save_path    

#--------------------------------------- EXTRACTING COLORS FROM PNG

def image_extraction(job_folder,colour_count=4):
    image_import_path = os.path.join(job_folder,'cover.png')

    extractionimg = ColorThief(image_import_path) # setup image for extraction

    palette = extractionimg.get_palette(color_count=4) # getting the 4 most dominant colours
    colorshex = []

    for r,g,b in palette: 
        hexvalue = '#' + format(r,'02x') + format(g,'02x') + format(b,'02x')# convert rgb values into hex
        colorshex.append(hexvalue)

    return colorshex
#-------------------------------------- Taking in lyrics





def lyrics(job_folder):
    
    def MMSS_Seconds(time_str):# converting from MMSS format to seconds for AE marker compatibility
        m, s = map(float, time_str.split(':'))
        return m * 60 + s
    
    initial_list = []
    final_list = []

    print("Enter lyrics in the format 'MM:SS lyric' ")
    print("When your finished typing lyrics type finish")
    print("If you mess up lyric input then type reset")

    while True:
        line = input(" >>Enter>> ").strip()

        if line.lower() == 'finish':#self explanatory
            break

        if line.lower() == 'reset':
            initial_list.clear()
            print("List has been reset")
            continue

        if not line: #skips empty lines
            continue

        try:   
            time_str,lyric_text = line.split(" ",1)#split the line ONCE into two sections, the time (before the space) and the lyrics (after)
            t= MMSS_Seconds(time_str) #assigning a variable to time input from user
            initial_list.append({'t':t, 'cur': lyric_text}) # appending this final structure to the list
        except ValueError:
            print("not the correct format")
            continue
        
    for i, lyric in enumerate(initial_list):
        prev=initial_list[i-1]["cur"] if i>0 else ""
        curr = lyric["cur"]
        next1= initial_list[i+1]["cur"] if i+1 < len(initial_list) else ""
        next2= initial_list[i+2]["cur"] if i+2 < len(initial_list) else ""

        final_list.append({
            "t": lyric["t"] ,
            "lyric_prev": prev,
            "lyric_current": curr,
            "lyric_next1": next1,
            "lyric_next2": next2 ,
        })
    lyrics_path = os.path.join(job_folder, "lyrics.txt")
    with open(lyrics_path, "w", encoding="utf-8") as f:
        json.dump(final_list, f, indent=4)



#-------------------------GENERATING JSON FILE FROM ALL DATA----------------------------------------