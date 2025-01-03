import discord
from discord.ext import commands
from plexapi.server import PlexServer

# === CONFIGURE THESE VALUES ===
DISCORD_BOT_TOKEN = "DISCORD BOT TOKEN"
PLEX_BASE_URL = "PLEX URL"
PLEX_TOKEN = "PLEX TOKEN"
DJ_ROLE_ID = 0  # Role allowed to skip, leave, and remove others' tracks
# ==============================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix=".", intents=intents)

# Create a Plex server instance
plex = PlexServer(PLEX_BASE_URL, PLEX_TOKEN)

bot.song_queue = []
bot.now_playing = None

def play_next_in_queue(ctx):
    """
    Plays the next song in the queue, if any.
    This is called automatically after the current song finishes or is skipped.
    """
    voice_client = ctx.voice_client
    if not voice_client:
        return
    
    if bot.song_queue:
        next_song = bot.song_queue.pop(0)  # Take the next track from the queue

        ffmpeg_options = {'options': '-vn'}
        source = discord.FFmpegPCMAudio(next_song["url"], **ffmpeg_options)

        def after_playing(error):
            if error:
                print(f"Error in after_playing: {error}")
            play_next_in_queue(ctx)  # Continue to next track

        voice_client.play(source, after=after_playing)
        bot.now_playing = next_song
        print(f"Now playing: {next_song['title']} by {next_song['artist']}")
    else:
        bot.now_playing = None

def user_has_dj_role(ctx):
    """
    Check if the user has the DJ role.
    """
    return any(role.id == DJ_ROLE_ID for role in ctx.author.roles)

def user_can_remove_track(ctx, track_info):
    """
    A user can remove a track if they are the DJ or
    if they originally requested the track.
    """
    return user_has_dj_role(ctx) or (track_info["requester_id"] == ctx.author.id)

@bot.event
async def on_ready():
    print(f"Logged in as {bot.user.name}")

@bot.command()
async def join(ctx):
    """
    Command the bot to join the user's voice channel.
    Example: !join
    """
    if ctx.author.voice is None or ctx.author.voice.channel is None:
        await ctx.send("You're not connected to a voice channel.")
        return

    channel = ctx.author.voice.channel
    if ctx.voice_client:
        await ctx.send("Bot is already in another voice channel")
    else:
        await channel.connect()

    await ctx.send(f"Joined the voice channel: {channel}")

@bot.command()
async def play(ctx, *, query: str):
    """
    Search for a track on Plex or play a specific content ID.
    
    Examples:
      - !play Bohemian Rhapsody
      - !play id 66452
    """
    voice_client = ctx.voice_client

    # If bot is not in a voice channel, try to join the user's channel
    if not voice_client:
        if ctx.author.voice and ctx.author.voice.channel:
            await ctx.author.voice.channel.connect()
            voice_client = ctx.voice_client
        else:
            await ctx.send("You must be in a voice channel or use '!join' first.")
            return

    # Direct Plex media ID
    track_info = None
    if query.lower().startswith("id "):
        # Extract the ID from the query
        content_id_str = query[3:].strip()
        if not content_id_str.isdigit():
            await ctx.send(f"Invalid ID format")
            return

        content_id = int(content_id_str)
        try:
            # Attempt to fetch the Plex item by ID
            plex_item = plex.fetchItem(content_id)

            track_info = {
                "title": plex_item.title,
                "artist": getattr(plex_item, "grandparentTitle", "Unknown Artist"),
                "url": plex_item.getStreamURL(),
                "requester_id": ctx.author.id,
                "requester_name": str(ctx.author),
            }
        except Exception as e:
            await ctx.send(f"Could not find or play item. Invalid ID?")
            return
    else:
        # Plex Search
        tracks = plex.search(query, mediatype="track")
        if not tracks:
            await ctx.send("No matching tracks found on Plex.")
            return

        # Take the first search result
        track = tracks[0]
        track_info = {
            "title": track.title,
            "artist": track.grandparentTitle,
            "url": track.getStreamURL(),
            "requester_id": ctx.author.id,
            "requester_name": str(ctx.author),
        }

    # If we have a valid track_info, either play immediately or queue it
    if not voice_client.is_playing():
        ffmpeg_options = {'options': '-vn'}
        source = discord.FFmpegPCMAudio(track_info["url"], **ffmpeg_options)

        def after_playing(error):
            if error:
                print(f"Error in after_playing: {error}")
            play_next_in_queue(ctx)

        voice_client.play(source, after=after_playing)
        bot.now_playing = track_info
        await ctx.send(f"Now playing: **{track_info['title']}** by **{track_info['artist']}**")
    else:
        bot.song_queue.append(track_info)
        await ctx.send(f"Added to queue: **{track_info['title']}** by **{track_info['artist']}**")

@bot.command()
async def queue(ctx):
    """
    Display up to 20 items in the queue.
    Example: !queue
    """
    if not bot.song_queue:
        await ctx.send("The queue is currently empty.")
        return

    # 20 item limit, so as not to flood the channel
    displayed_tracks = bot.song_queue[:20]
    msg_lines = ["**Current Queue:**"]
    for i, item in enumerate(displayed_tracks, start=1):
        msg_lines.append(
            f"{i}. **{item['title']}** by {item['artist']} "
            f"(requested by {item['requester_name']})"
        )

    if len(bot.song_queue) > 20:
        msg_lines.append(f"...and {len(bot.song_queue) - 20} more.")

    await ctx.send("\n".join(msg_lines))

@bot.command()
async def remove(ctx, index: int):
    """
    Remove a specific track from the queue by its position number.
    You can remove it if you're the DJ or if you requested the track.
    Example: !remove 2
    """
    if index < 1 or index > len(bot.song_queue):
        await ctx.send("Invalid track number.")
        return

    track_to_remove = bot.song_queue[index - 1]

    # Check permissions
    if not user_can_remove_track(ctx, track_to_remove):
        await ctx.send("You don't have permission to remove this track from the queue.")
        return

    removed_track = bot.song_queue.pop(index - 1)
    await ctx.send(
        f"Removed from queue: **{removed_track['title']}** by {removed_track['artist']} "
        f"(requested by {removed_track['requester_name']})."
    )

@bot.command()
async def skip(ctx):
    """
    Skip the currently playing track. Only allowed if you have the DJ role.
    Example: !skip
    """
    if not user_has_dj_role(ctx):
        await ctx.send("You don't have permission to use this command.")
        return

    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()
        await ctx.send("Skipped the current track.")
    else:
        await ctx.send("There is nothing playing to skip.")

@bot.command()
async def stop(ctx):
    """
    Stop the currently playing track and clear the queue.
    Example: !stop

    Restricted to DJs.
    """
    if not user_has_dj_role(ctx):
        await ctx.send("You don't have permission to use this command.")
        return
    
    voice_client = ctx.voice_client
    if voice_client and voice_client.is_playing():
        voice_client.stop()

    bot.song_queue.clear()
    bot.now_playing = None
    await ctx.send("Stopped playback and cleared the queue.")

@bot.command()
async def leave(ctx):
    """
    Leave the current voice channel.
    Example: !leave

    Restricted to DJs.
    """
    if not user_has_dj_role(ctx):
        await ctx.send("You don't have permission to use this command.")
        return

    voice_client = ctx.voice_client
    if voice_client:
        await voice_client.disconnect()
        bot.song_queue.clear()
        bot.now_playing = None
        await ctx.send("Left the voice channel and cleared the queue.")
    else:
        await ctx.send("I'm not in a voice channel.")

bot.run(DISCORD_BOT_TOKEN)
