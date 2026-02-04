import discord
from discord.ext import commands
from plexapi.server import PlexServer
import requests
import xml.etree.ElementTree as ET

# === CONFIGURE THESE VALUES ===
DISCORD_BOT_TOKEN = ""
PLEX_BASE_URL = ""
PLEX_TOKEN = ""
DJ_ROLE_ID =   # Role allowed to skip, leave, and remove others' tracks
# ==============================

intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="p.", intents=intents)

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
async def play(ctx, *, query: str = ""):
    """
    Search for a track on Plex, play a specific content ID, or play a URL/attachment.
    
    Examples:
      - p.play Bohemian Rhapsody
      - p.play id 66452
      - p.play https://example.com/song.mp3
      - p.play (with a file attached)
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

    # Nothing to play — no query, no URL, no attachment
    if not query and not ctx.message.attachments:
        await ctx.send("Provide a search term, URL, or attach a file to play.")
        return

    track_info = None

    # Check for attached files
    if ctx.message.attachments:
        attachment = ctx.message.attachments[0]
        track_info = {
            "title": attachment.filename,
            "artist": "Uploaded File",
            "url": attachment.url,
            "requester_id": ctx.author.id,
            "requester_name": str(ctx.author),
        }
    # Check for a direct URL in the query
    elif query.lower().startswith(("http://", "https://")):
        url = query.split()[0]
        from urllib.parse import urlparse, unquote
        path = urlparse(url).path
        filename = unquote(path.split("/")[-1]) if path else "Unknown"
        track_info = {
            "title": filename or "Linked File",
            "artist": "Direct Link",
            "url": url,
            "requester_id": ctx.author.id,
            "requester_name": str(ctx.author),
        }
    # Direct Plex media ID
    elif query.lower().startswith("id "):
        content_id_str = query[3:].strip()
        if not content_id_str.isdigit():
            await ctx.send(f"Invalid ID format")
            return

        content_id = int(content_id_str)
        try:
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

@bot.command()
async def fuckoff(ctx):
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

@bot.command()
async def search(ctx, *, query: str):
    """
    Search for tracks on Plex using the hubs/search API.
    Use reactions to navigate pages, then reply with a number to play.
    Example: .search Bohemian Rhapsody
    """
    # Use the raw Plex API endpoint like your website does
    import urllib.parse
    encoded_query = urllib.parse.quote(query)
    
    search_url = (
        f"{PLEX_BASE_URL}/hubs/search"
        f"?query={encoded_query}"
        f"&includeCollections=1"
        f"&includeExternalMedia=1"
        f"&limit=30"
        f"&X-Plex-Token={PLEX_TOKEN}"
    )
    
    try:
        response = requests.get(search_url)
        response.raise_for_status()
    except requests.RequestException as e:
        await ctx.send(f"Error searching Plex: {e}")
        return
    
    # Parse the XML response
    root = ET.fromstring(response.content)
    
    # Find all track results - they're in a Hub with type="track"
    tracks = []
    for hub in root.findall(".//Hub[@type='track']"):
        for track in hub.findall(".//Track"):
            track_data = {
                "ratingKey": track.get("ratingKey"),
                "title": track.get("title", "Unknown Title"),
                "artist": track.get("grandparentTitle", "Unknown Artist"),
                "album": track.get("parentTitle", "Unknown Album"),
            }
            tracks.append(track_data)
    
    if not tracks:
        await ctx.send("No matching tracks found on Plex.")
        return
    
    # Limit to 30
    tracks = tracks[:30]
    
    # Store search results for this user
    if not hasattr(bot, 'search_results'):
        bot.search_results = {}
    
    bot.search_results[ctx.author.id] = {
        "tracks": tracks,
        "query": query,
        "page": 0,
        "ctx": ctx
    }
    
    # Build and send the first page
    embed = build_search_embed(tracks, query, 0)
    search_msg = await ctx.send(embed=embed)
    
    # Store message reference
    bot.search_results[ctx.author.id]["message"] = search_msg
    
    # Add navigation reactions if more than one page
    total_pages = (len(tracks) + 9) // 10
    if total_pages > 1:
        await search_msg.add_reaction("⬅️")
        await search_msg.add_reaction("➡️")
    await search_msg.add_reaction("❌")


def build_search_embed(tracks, query, page):
    """
    Build an embed for a specific page of search results.
    """
    total_pages = (len(tracks) + 9) // 10
    start_idx = page * 10
    end_idx = min(start_idx + 10, len(tracks))
    page_tracks = tracks[start_idx:end_idx]
    
    embed = discord.Embed(
        title=f"🔍 Search Results for: {query}",
        description=f"Reply with a number to play that track.\nPage {page + 1}/{total_pages}",
        color=discord.Color.blurple()
    )
    
    lines = []
    for i, track in enumerate(page_tracks, start=start_idx + 1):
        # Truncate long titles/artists/albums
        title = track['title'][:50] + "..." if len(track['title']) > 50 else track['title']
        artist = track['artist'][:30] + "..." if len(track['artist']) > 30 else track['artist']
        album = track['album'][:30] + "..." if len(track['album']) > 30 else track['album']
        
        lines.append(f"**{i}.** {title}\n　　by *{artist}* — {album}")
    
    field_value = "\n".join(lines)
    
    # Safety check: truncate if still over 1024
    if len(field_value) > 1024:
        field_value = field_value[:1020] + "..."
    
    embed.add_field(name="Tracks", value=field_value, inline=False)
    embed.set_footer(text="⬅️ Previous | ➡️ Next | ❌ Cancel")
    
    return embed

@bot.event
async def on_reaction_add(reaction, user):
    """
    Handle pagination reactions on search results.
    """
    # Ignore bot's own reactions
    if user.bot:
        return
    
    # Check if this user has active search results
    if not hasattr(bot, 'search_results') or user.id not in bot.search_results:
        return
    
    search_data = bot.search_results[user.id]
    
    # Verify it's the correct message
    if reaction.message.id != search_data["message"].id:
        return
    
    tracks = search_data["tracks"]
    total_pages = (len(tracks) + 9) // 10
    current_page = search_data["page"]
    
    if str(reaction.emoji) == "➡️":
        # Next page
        if current_page < total_pages - 1:
            search_data["page"] += 1
            embed = build_search_embed(tracks, search_data["query"], search_data["page"])
            await search_data["message"].edit(embed=embed)
    
    elif str(reaction.emoji) == "⬅️":
        # Previous page
        if current_page > 0:
            search_data["page"] -= 1
            embed = build_search_embed(tracks, search_data["query"], search_data["page"])
            await search_data["message"].edit(embed=embed)
    
    elif str(reaction.emoji) == "❌":
        # Cancel search
        await search_data["message"].delete()
        del bot.search_results[user.id]
        return
    
    # Remove the user's reaction to keep it clean
    try:
        await reaction.remove(user)
    except discord.errors.Forbidden:
        pass  # Bot may not have permission

@bot.event
async def on_message(message):
    if message.author.bot:
        await bot.process_commands(message)
        return
    
    if hasattr(bot, 'search_results') and message.author.id in bot.search_results:
        content = message.content.strip()
        if content.isdigit():
            selection = int(content)
            search_data = bot.search_results[message.author.id]
            tracks = search_data["tracks"]
            
            if 1 <= selection <= len(tracks):
                track = tracks[selection - 1]
                ctx = search_data["ctx"]
                
                # Delete messages
                try:
                    await search_data["message"].delete()
                except:
                    pass
                try:
                    await message.delete()
                except discord.errors.Forbidden:
                    pass
                
                del bot.search_results[message.author.id]
                
                # Fetch the actual Plex item using ratingKey
                try:
                    plex_item = plex.fetchItem(int(track["ratingKey"]))
                    stream_url = plex_item.getStreamURL()
                except Exception as e:
                    await ctx.send(f"Error fetching track from Plex: {e}")
                    return
                
                track_info = {
                    "title": track["title"],
                    "artist": track["artist"],
                    "url": stream_url,
                    "requester_id": message.author.id,
                    "requester_name": str(message.author),
                }
                
                voice_client = ctx.voice_client
                
                if not voice_client:
                    if message.author.voice and message.author.voice.channel:
                        await message.author.voice.channel.connect()
                        voice_client = ctx.voice_client
                    else:
                        await ctx.send("You must be in a voice channel to play music.")
                        return
                
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
                
                return
    
    # Process other commands normally
    await bot.process_commands(message)

bot.run(DISCORD_BOT_TOKEN)
