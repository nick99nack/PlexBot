************************************
PlexBot: Plex music bot for Discord
************************************

Requirements: Python 3.x and ffmpeg

Installation:
   1. Install discord.py and plexapi using pip
   2. Fill out your Discord bot token, Plex URL & token, and the ID of the DJ role
      in your server.
   3. Run: python3 plexbot.py
   4. ???
   5. Profit!


Commands:
       join - joins the bot to a voice channel
       play - searches for and plays a song (bot will join a voice channel if it's 
              not in one already)
    play id - Plays a track based on its Plex ID
      queue - shows the song queue, max of 20 items
 remove [#] - removes the selected track from the queue
       skip - skips the current track (only for DJs and song requesters)
       stop - stops the playing track and clears the queue
      leave - makes the bot leave the voice channel


Note to purists: AI assistance was used in the making of this bot.
