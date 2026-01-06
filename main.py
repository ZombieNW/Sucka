import os
import discord
from dotenv import load_dotenv
from datetime import datetime
from pydub import AudioSegment

load_dotenv()

# Config
TOKEN = os.getenv('DISCORD_TOKEN')
ADMIN_ID = os.getenv('ADMIN_ID')
GUILD_ID = os.getenv('GUILD_ID')
RECORDINGS_DIR = "recordings"

# Bot Setup
intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = discord.Bot(intents=intents, guild_ids=[GUILD_ID])

# Global Variables
voice_client = None
recording_start_time = None

# Custom Superclass of WaveSink that timestamps when users start talking
class TimestampedSink(discord.sinks.WaveSink):
    def __init__(self):
        super().__init__()
        self.user_start_times = {}
        self.recording_start = None
    
    def write(self, data, user):
        if user not in self.user_start_times:
            if self.recording_start is None:
                self.recording_start = datetime.now()
            
            # Calculate offset from recording start
            offset_ms = (datetime.now() - self.recording_start).total_seconds() * 1000
            self.user_start_times[user] = offset_ms
            print(f"[{offset_ms:.0f}ms] {user} Started Speaking")
        
        super().write(data, user)

# Process Audio Track
def process_audio_track(user_id, audio_data, start_offset_ms, total_duration_ms, member_name):
    pcm_data = audio_data[44:] # Extract raw PCM

    # Create AudioSegment from PCM (Discord uses 48kHz, 16-bit, Stereo PCM)
    user_audio = AudioSegment(
        data=pcm_data,
        sample_width=2,
        frame_rate=48000,
        channels=2
    )

    audio_duration = len(user_audio)

    # Build Timeline:
    # [silence before] => [audio] => [silence after]
    start_silence = AudioSegment.silent(duration=start_offset_ms, frame_rate=48000)

    end_time = start_offset_ms + audio_duration
    end_silence_duration = max(0, total_duration_ms - end_time)
    end_silence = AudioSegment.silent(duration=end_silence_duration, frame_rate=48000)

    full_track = start_silence + user_audio + end_silence # The Final Audio Track :tm:

    # Ensure Duration
    if len(full_track) > total_duration_ms:
        full_track = full_track[:total_duration_ms]

    # Log Track Info
    print(f"\n{member_name}")
    print(f"    Starts at {start_offset_ms}ms")
    print(f"    Audio_duration: {len(full_track)}ms")
    print(f"    Final Track: {len(full_track)}ms")

    return full_track

@bot.event
async def on_ready():
    print(f'{bot.user} online !')
    print("=" * 60)
    os.makedirs(RECORDINGS_DIR, exist_ok=True)

@bot.slash_command(
    name="record",
    description="Starts a recording session",
)
async def record(ctx):
    global voice_client, recording_start_time
    
    # Auth Check
    if ctx.author.id != ADMIN_ID:
        await ctx.respond("Access Denied", ephemeral=True)
        return

    # VC Check
    if not ctx.author.voice:
        await ctx.respond("You must be in a voice channel", ephemeral=True)
        return
    
    # Recording Check
    if voice_client and voice_client.recording:
        await ctx.respond("Already Recording", ephemeral=True)
        return
    
    # Connect & Record
    channel = ctx.author.voice.channel
    voice_client = await channel.connect()
    recording_start_time = datetime.now()

    sink = TimestampedSink()

    # Processes & Saves Audio
    async def finished_callback(sink, channel):
        total_duration_ms = int((datetime.now() - recording_start_time).total_seconds() * 1000)

        print(f"\n{'=' * 60}")
        print(f"Processing {len(sink.audio_data)} Track")
        print(f"Total Recording Duration: {total_duration_ms}ms")
        print(f"\n{'=' * 60}")

        timestamp = recording_start_time.strftime("%Y-%m-%d_%H-%M-%S")
        saved_count = 0

        for user_id, audio in sink.audio_data.items():
            try:
                # Get User Info
                member = await ctx.guild.fetch_member(user_id)
                name = member.display_name if member else str(user_id)

                # Get Timing Info
                start_offset_ms = int(sink.user_start_times.get(user_id, 0))

                # Get Audio Data
                audio.file.seek(0)
                audio_bytes = audio.file.read()

                # Process Track
                full_track = process_audio_track(
                    user_id,
                    audio_bytes,
                    start_offset_ms,
                    total_duration_ms,
                    name
                )

                # Save Audio
                filename = f"{RECORDINGS_DIR}/{name}_{timestamp}.wav"
                full_track.export(filename, format="wav")
                print(f"  ✓ Saved: {filename}")

                saved_count += 1
            except Exception as e:
                print(f"  ✗ Error processing user {user_id}: {e}")
        
        print(f"\n{'=' * 60}")
        print(f"✓ Saved {saved_count} synced tracks ({total_duration_ms / 1000}s)")
    
    voice_client.start_recording(sink, finished_callback, channel)
    await ctx.respond(f"Recording Started - {channel.name}", ephemeral=True)

@bot.slash_command(name="stop", description="Stop recording")
async def stop(ctx):
    global voice_client

    if not voice_client or not voice_client.recording:
        await ctx.respond("Not Recording", ephemeral=True)
        return

    await ctx.respond("Stopping & Processing...", ephemeral=True)
    voice_client.stop_recording()
    await voice_client.disconnect()
    voice_client = None

@bot.event
async def on_application_command_error(ctx, error):
    await ctx.respond("Error: " + str(error), ephemeral=True)

if __name__ == "__main__":
    print("=" * 60)
    print("It's Sucka !")
    bot.run(TOKEN)