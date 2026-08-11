import asyncio
import functools
import os
import discord
from discord.ext import commands
import yt_dlp

# ------------------------------------------------------------------
# اعدادات عامة
# ------------------------------------------------------------------

# التوكن يقرا من متغير بيئة اسمه DISCORD_TOKEN
# هذا هو الاسلوب الصحيح عند الرفع على استضافه متل Railway
# بدل ما تكتب التوكن مباشره بالكود
TOKEN = os.environ.get("DISCORD_TOKEN")
PREFIX = os.environ.get("BOT_PREFIX", "")  # فاضي يعني بدون رمز قبل الامر، تقدر تحطه لو حبيت

intents = discord.Intents.default()
intents.message_content = True
intents.voice_states = True

bot = commands.Bot(command_prefix=PREFIX, intents=intents, help_command=None)

YDL_OPTIONS = {
    "format": "bestaudio/best",
    "noplaylist": True,
    "quiet": True,
    "default_search": "ytsearch",
    "source_address": "0.0.0.0",
}

FFMPEG_OPTIONS = {
    "before_options": "-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5",
    "options": "-vn",
}

# حالة كل روم صوتي على حدة (قائمة الانتظار وعناصر التكرار والصوت)
guild_states = {}


def get_state(guild_id):
    if guild_id not in guild_states:
        guild_states[guild_id] = {
            "queue": [],
            "current": None,
            "loop": False,
            "volume": 0.5,
            "text_channel_id": None,  # شات الروم الي البوت مقيد يشتغل فيه بس
        }
    return guild_states[guild_id]


# ------------------------------------------------------------------
# دوال مساعدة لجلب الصوت من يوتيوب
# ------------------------------------------------------------------

async def search_song(query):
    loop = asyncio.get_event_loop()
    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
        func = functools.partial(ydl.extract_info, query, download=False)
        info = await loop.run_in_executor(None, func)
        if "entries" in info:
            info = info["entries"][0]
        return {
            "title": info.get("title", "مقطع بدون اسم"),
            "url": info.get("url"),
            "webpage_url": info.get("webpage_url", query),
            "duration": info.get("duration", 0),
        }


def format_duration(seconds):
    if not seconds:
        return "غير معروف"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


# ------------------------------------------------------------------
# منطق تشغيل قائمة الانتظار
# ------------------------------------------------------------------

def play_next(guild, error=None):
    if error:
        print(f"خطا بالتشغيل: {error}")

    state = get_state(guild.id)
    vc = guild.voice_client
    if vc is None:
        return

    if state["loop"] and state["current"] is not None:
        state["queue"].insert(0, state["current"])

    if state["queue"]:
        song = state["queue"].pop(0)
        state["current"] = song
        source = discord.PCMVolumeTransformer(
            discord.FFmpegPCMAudio(song["url"], **FFMPEG_OPTIONS),
            volume=state["volume"],
        )
        vc.play(source, after=lambda e: play_next(guild, e))
    else:
        state["current"] = None


# ------------------------------------------------------------------
# احداث البوت
# ------------------------------------------------------------------

@bot.event
async def on_ready():
    print(f"تم تسجيل الدخول باسم {bot.user}")


# ------------------------------------------------------------------
# تقييد الاوامر بحيث تشتغل فقط داخل شات الروم الي دخل عليه البوت
# امر come معفى من هذا الشرط لانه هو الي يحدد الروم من الاساس
# ------------------------------------------------------------------

@bot.check
async def restrict_to_room_chat(ctx):
    if ctx.command is not None and ctx.command.name == "come":
        return True

    if ctx.guild is None:
        return False

    state = guild_states.get(ctx.guild.id)
    if not state or not state.get("text_channel_id"):
        return False

    return ctx.channel.id == state["text_channel_id"]


@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.MissingPermissions):
        # تجاهل بصمت، ما نرسل اي رد لغير الادمن
        pass
    elif isinstance(error, commands.CheckFailure):
        # تجاهل بصمت، الامر ارسل بمكان غير مسموح او البوت لسا ما دخل
        pass
    else:
        print(f"خطا غير متوقع: {error}")


# ------------------------------------------------------------------
# امر استدعاء البوت للروم: come (للادمن فقط)
# ------------------------------------------------------------------

@bot.command(name="come", aliases=["احضر", "تعال"])
@commands.has_permissions(administrator=True)
async def come(ctx):
    if ctx.author.voice is None:
        await ctx.send("لازم تكون داخل روم صوتي حتى يقدر البوت يدخل")
        return

    channel = ctx.author.voice.channel
    vc = ctx.voice_client

    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    state = get_state(ctx.guild.id)
    state["text_channel_id"] = channel.id

    await channel.send(
        "تم دخول البوت لهذا الروم من الان الاوامر تشتغل هنا فقط ولا تشتغل بأي شات اخر"
    )


# ------------------------------------------------------------------
# امر التشغيل: play | p | شغل | ش
# ------------------------------------------------------------------

@bot.command(name="play", aliases=["p", "شغل", "ش"])
async def play(ctx, *, query: str = None):
    if query is None:
        await ctx.send("اكتب اسم الاغنيه او رابطها بعد الامر")
        return

    if ctx.author.voice is None:
        await ctx.send("لازم تكون داخل روم صوتي حتى يشتغل البوت")
        return

    channel = ctx.author.voice.channel
    vc = ctx.voice_client

    if vc is None:
        vc = await channel.connect()
    elif vc.channel != channel:
        await vc.move_to(channel)

    msg = await ctx.send("جاري البحث عن المقطع")

    try:
        song = await search_song(query)
    except Exception:
        await msg.edit(content="ما قدرت الاقي المقطع تاكد من الاسم او الرابط")
        return

    state = get_state(ctx.guild.id)
    state["queue"].append(song)

    if vc.is_playing() or vc.is_paused():
        await msg.edit(content=f"تمت اضافه المقطع للقائمه {song['title']}")
    else:
        await msg.edit(content=f"جاري تشغيل {song['title']}")
        play_next(ctx.guild)


# ------------------------------------------------------------------
# امر التخطي: skip | s | تخطي | خطي
# ------------------------------------------------------------------

@bot.command(name="skip", aliases=["s", "تخطي", "خطي"])
async def skip(ctx):
    vc = ctx.voice_client
    if vc is None or not (vc.is_playing() or vc.is_paused()):
        await ctx.send("ما فيه شي يشتغل حاليا")
        return
    vc.stop()
    await ctx.send("تم الانتقال للمقطع التالي")


# ------------------------------------------------------------------
# الايقاف الموقت: pause | pa
# ------------------------------------------------------------------

@bot.command(name="pause", aliases=["pa", "ايقاف مؤقت", "توقف مؤقت"])
async def pause(ctx):
    vc = ctx.voice_client
    if vc is None or not vc.is_playing():
        await ctx.send("ما فيه شي يشتغل حاليا")
        return
    vc.pause()
    await ctx.send("تم ايقاف المقطع مؤقتا")


@bot.command(name="resume", aliases=["r", "استمرار", "كمل"])
async def resume(ctx):
    vc = ctx.voice_client
    if vc is None or not vc.is_paused():
        await ctx.send("ما فيه شي متوقف حاليا")
        return
    vc.resume()
    await ctx.send("تم استئناف التشغيل")


# ------------------------------------------------------------------
# الايقاف الكامل: stop | وقف
# ------------------------------------------------------------------

@bot.command(name="stop", aliases=["وقف"])
async def stop(ctx):
    vc = ctx.voice_client
    if vc is None:
        await ctx.send("البوت مو داخل روم صوتي")
        return
    state = get_state(ctx.guild.id)
    state["queue"].clear()
    state["current"] = None
    state["loop"] = False
    vc.stop()
    await ctx.send("تم ايقاف تشغيل الاغاني والبوت باقي بالروم")


# ------------------------------------------------------------------
# اخراج البوت من الروم نهائيا: leave (للادمن فقط)
# ------------------------------------------------------------------

@bot.command(name="leave", aliases=["اخرج", "طلع"])
@commands.has_permissions(administrator=True)
async def leave(ctx):
    vc = ctx.voice_client
    if vc is None:
        await ctx.send("البوت مو داخل اي روم اصلا")
        return
    state = get_state(ctx.guild.id)
    state["queue"].clear()
    state["current"] = None
    state["loop"] = False
    state["text_channel_id"] = None
    vc.stop()
    await vc.disconnect()
    await ctx.send("تم اخراج البوت من الروم، يمكنك استدعاءه لروم ثاني بامر come")


# ------------------------------------------------------------------
# مستوى الصوت: volume | v | صوت | ص
# ------------------------------------------------------------------

@bot.command(name="volume", aliases=["v", "صوت", "ص"])
async def volume(ctx, level: int = None):
    state = get_state(ctx.guild.id)
    vc = ctx.voice_client

    if level is None:
        await ctx.send(f"مستوى الصوت الحالي {int(state['volume'] * 100)}")
        return

    if level < 0 or level > 100:
        await ctx.send("الرجاء كتابه رقم بين 0 و 100")
        return

    state["volume"] = level / 100
    if vc is not None and vc.source is not None:
        vc.source.volume = state["volume"]

    await ctx.send(f"تم تعديل مستوى الصوت الى {level}")


# ------------------------------------------------------------------
# المقطع الحالي: nowplaying | np
# ------------------------------------------------------------------

@bot.command(name="nowplaying", aliases=["np", "المقطع الحالي"])
async def nowplaying(ctx):
    state = get_state(ctx.guild.id)
    song = state["current"]
    if song is None:
        await ctx.send("ما فيه شي يشتغل حاليا")
        return
    await ctx.send(
        f"يتم الان تشغيل {song['title']}\n"
        f"المدة {format_duration(song['duration'])}\n"
        f"الرابط {song['webpage_url']}"
    )


# ------------------------------------------------------------------
# التكرار: loop | تكرار
# ------------------------------------------------------------------

@bot.command(name="loop", aliases=["تكرار"])
async def loop(ctx):
    state = get_state(ctx.guild.id)
    state["loop"] = not state["loop"]
    if state["loop"]:
        await ctx.send("تم تفعيل تكرار المقطع")
    else:
        await ctx.send("تم تعطيل تكرار المقطع")


# ------------------------------------------------------------------
# تشغيل البوت
# ------------------------------------------------------------------

if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit(
            "لم يتم العثور على التوكن، تاكد من اضافه متغير البيئه DISCORD_TOKEN"
        )
    bot.run(TOKEN)
