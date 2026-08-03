#!/usr/bin/env python3
"""
Build i18n/zh_TW/LC_MESSAGES/musicbot_messages.po for MusicBot.

Keys below are the *escaped* msgid exactly as it appears inside the quotes of the
reference catalog (so `\n` here is a literal backslash-n, matching the .po file).
Any key that does not match a real msgid is reported as UNMATCHED -- treat that as
a bug in this file, not something to ignore.

Untranslated entries are written as empty msgstr, which gettext falls back to the
English source for. Partial coverage is safe.
"""
import re
import sys
import pathlib

T = {}

# ---------------------------------------------------------------- voice / connection
T[r"Member is not voice-enabled and cannot use this command."] = r"這位成員沒有開啟語音，無法使用這個指令。"
T[r"You cannot use this command when not in the voice channel."] = r"你不在語音頻道裡，不能用這個指令。"
T[r"MusicBot does not have permission to Connect in channel:  `%(name)s`"] = r"MusicBot 沒有權限連進頻道 `%(name)s`"
T[r"MusicBot does not have permission to Speak in channel:  `%(name)s`"] = r"MusicBot 沒有權限在頻道 `%(name)s` 說話"
T[r"MusicBot could not connect to the channel.\nTry again later, or restart the bot if this continues."] = r"MusicBot 連不進這個頻道。\n請稍後再試，如果一直這樣就重啟機器人。"
T[r"MusicBot connection to voice was cancelled. This is odd. Maybe restart?"] = r"MusicBot 的語音連線被取消了，這不太正常，也許該重啟一下？"
T[r"MusicBot does not have permission to speak."] = r"MusicBot 沒有說話的權限。"
T[r"MusicBot could not request to speak."] = r"MusicBot 無法送出發言請求。"
T[r"The bot is not in a voice channel.\nUse the summon command to bring the bot to your voice channel."] = r"機器人不在語音頻道裡。\n用 summon 指令把它叫進你的語音頻道。"
T[r"Something is wrong, we didn't get the VoiceClient."] = r"有點不對勁，沒有取得 VoiceClient。"
T[r"You are not connected to voice. Try joining a voice channel!"] = r"你沒有連上語音，先加入一個語音頻道吧！"
T[r"Connected to `%(channel)s`"] = r"已連線到 `%(channel)s`"
T[r"Tell MusicBot to join the channel you're in."] = r"叫 MusicBot 加入你所在的頻道。"
T[r"This command requires you to be in a Voice channel."] = r"這個指令需要你在語音頻道裡才能用。"
T[r"You must be in a voice channel to use this command."] = r"你必須在語音頻道裡才能用這個指令。"
T[r"You cannot use this bot in private messages."] = r"這個機器人不能在私訊裡使用。"
T[r"Leaving voice channel %(channel)s due to inactivity."] = r"因為閒置太久，離開語音頻道 %(channel)s。"
T[r"Disconnected from server `%(guild)s`"] = r"已從伺服器 `%(guild)s` 斷線"
T[r"Not currently connected to server `%(guild)s`"] = r"目前沒有連線到伺服器 `%(guild)s`"
T[r"Force MusicBot to disconnect from the discord server."] = r"強制 MusicBot 從這個 Discord 伺服器斷線。"

# ---------------------------------------------------------------- now playing
T[r"Skipping next song `%(title)s` as requester `%(user)s` is not in voice!"] = r"跳過下一首 `%(title)s`，因為點歌的 `%(user)s` 不在語音頻道裡！"
T[r"%(mention)s - your song `%(title)s` is now playing in %(channel)s!"] = r"%(mention)s － 你點的 `%(title)s` 正在 %(channel)s 播放！"
T[r"Now playing in %(channel)s: `%(title)s` added by %(author)s!"] = r"%(channel)s 正在播放：`%(title)s`（%(author)s 點的）"
T[r"Now playing automatically added entry `%(title)s` in %(channel)s!"] = r"%(channel)s 正在播放自動加入的曲目 `%(title)s`"
T[r"Skipping songs added by %(user)s as they are not in voice!"] = r"跳過 %(user)s 點的歌，因為人不在語音頻道裡！"
T[r"Playback failed for song `%(song)s` due to an error:\n```\n%(error)s```"] = r"`%(song)s` 播放失敗，發生錯誤：\n```\n%(error)s```"
T[r"Show information on what is currently playing."] = r"顯示目前正在播放的內容。"
T[r"Now playing"] = r"現正播放"
T[r"Currently streaming:"] = r"正在串流："
T[r"Currently playing:"] = r"正在播放："
T[r"Added By:"] = r"點播者："
T[r"Progress:"] = r"進度："
T[r"URL:"] = r"網址："
T[r"There is nothing currently playing. Play something with a play command."] = r"現在沒有在播任何東西，用 play 指令點首歌吧。"
T[r"No songs are currently playing. Play something with a play command."] = r"現在沒有在播任何歌，用 play 指令點首歌吧。"

# ---------------------------------------------------------------- play / enqueue
T[r"Add a song to be played in the queue. If no song is playing or paused, playback will be started.\n\nYou may supply a URL to a video or audio file or the URL of a service supported by yt-dlp.\nPlaylist links will be extracted into multiple links and added to the queue.\nIf you enter a non-URL, the input will be used as search criteria on YouTube and the first result played.\nMusicBot also supports Spotify URIs and URLs, but audio is fetched from YouTube regardless.\n"] = r"把一首歌加進播放隊列。如果目前沒有在播或已暫停，就會開始播放。\n\n你可以給影片或音訊檔的網址，或任何 yt-dlp 支援的服務網址。\n播放清單連結會被展開成多首並全部加進隊列。\n如果輸入的不是網址，就會拿去 YouTube 搜尋並播放第一筆結果。\nMusicBot 也支援 Spotify 的 URI 與網址，但音訊一律還是從 YouTube 抓。\n"
T[r"Play command that shuffles playlist entries before adding them to the queue.\n"] = r"播放指令，但會先把播放清單的曲目打亂再加進隊列。\n"
T[r"Shuffled playlist items into the queue from `%(request)s`"] = r"已把 `%(request)s` 的曲目打亂後加進隊列"
T[r"A play command that adds the song as the next to play rather than last.\nRead help for the play command for information on supported inputs.\n"] = r"播放指令，但把歌插到「下一首」而不是隊列最後。\n支援的輸入格式請看 play 指令的說明。\n"
T[r"A play command which skips any current song and plays immediately.\nRead help for the play command for information on supported inputs.\n"] = r"播放指令，會跳過目前這首直接播放新的。\n支援的輸入格式請看 play 指令的說明。\n"
T[r"Enqueued **%(number)s** songs to be played.\nPosition in queue: %(position)s"] = r"已加入 **%(number)s** 首歌到隊列。\n隊列位置：%(position)s"
T[r"Enqueued `%(track)s` to be played.\nPosition in queue: %(position)s"] = r"已把 `%(track)s` 加進隊列。\n隊列位置：%(position)s"
T[r"Playing next!"] = r"下一首就是它！"
T[r"%(position)s - estimated time until playing: `%(eta)s`"] = r"第 %(position)s 位 － 預估還要等：`%(eta)s`"
T[r"%(position)s - cannot estimate time until playing."] = r"第 %(position)s 位 － 無法預估還要等多久。"
T[r"Song duration exceeds limit (%(length)s > %(max)s)"] = r"歌曲長度超過上限（%(length)s 秒 > %(max)s 秒）"
T[r"No songs were added, all songs were over max duration (%(max)s seconds)"] = r"沒有加入任何歌曲，全部都超過長度上限（%(max)s 秒）"
T[r"You have reached your enqueued song limit (%(max)s)"] = r"你排隊的歌已達上限（%(max)s 首）"
T[r"You have reached your playlist item limit (%(max)s)"] = r"你的播放清單曲目數已達上限（%(max)s 首）"
T[r"You are not allowed to request playlists"] = r"你沒有權限點播放清單"
T[r"Playlist has too many entries (%(songs)s but max is %(max)s)"] = r"播放清單曲目太多（%(songs)s 首，上限是 %(max)s 首）"
T[r"The playlist entries will exceed your queue limit.\nThere are %(songs)s in the list, and %(queued)s already in queue.\nThe limit is %(max)s for your group."] = r"這個播放清單會讓你超過排隊上限。\n清單裡有 %(songs)s 首，你已經排了 %(queued)s 首。\n你所屬群組的上限是 %(max)s 首。"
T[r"That video cannot be played. Try using the stream command."] = r"這部影片沒辦法播放，試試看用 stream 指令。"
T[r"Failed to extract info due to error:\n%(raw_error)s"] = r"擷取資訊失敗，發生錯誤：\n%(raw_error)s"
T[r"The supplied song link is invalid"] = r"提供的歌曲連結無效"
T[r"Spotify URL is invalid or not currently supported."] = r"Spotify 網址無效，或目前不支援。"
T[r"Detected a Spotify URL, but Spotify is not enabled."] = r"偵測到 Spotify 網址，但 Spotify 功能沒有啟用。"
T[r"Local media playback is not enabled."] = r"本機媒體播放功能沒有啟用。"
T[r"This link contains a Playlist ID:\n`%(url)s`\n\nDo you want to queue the playlist too?"] = r"這個連結含有播放清單 ID：\n`%(url)s`\n\n要連整個播放清單一起加入嗎？"
T[r"The requested song `%(subject)s` is blocked by the song block list."] = r"你點的 `%(subject)s` 被歌曲封鎖清單擋下了。"
T[r"Bot was previously paused, resuming playback now."] = r"機器人先前是暫停狀態，現在恢復播放。"
T[r"Alright, coming right up!"] = r"好，馬上來！"
T[r"Added song [%(track)s](%(url)s) to the queue."] = r"已把 [%(track)s](%(url)s) 加進隊列。"
T[r"Search returned no results with %(extractor)s for:  %(url)s"] = r"用 %(extractor)s 搜尋不到結果：%(url)s"

# ---------------------------------------------------------------- stream
T[r"Add a media URL to the queue as a Stream.\nThe URL may be actual streaming media, like Twitch, Youtube, or a shoutcast like service.\nYou can also use non-streamed media to play it without downloading it.\nNote: FFmpeg may drop the stream randomly or if connection hiccups happen.\n"] = r"以「串流」方式把媒體網址加進隊列。\n網址可以是真正的串流來源，像 Twitch、YouTube 或 shoutcast 之類的服務。\n也可以拿來播非串流的媒體，好處是不用先下載。\n注意：FFmpeg 可能會隨機斷流，網路不穩時也會。\n"
T[r"Streaming playlists is not yet supported."] = r"還不支援串流整個播放清單。"
T[r"Now streaming track `%(track)s`"] = r"開始串流 `%(track)s`"
T[r"Cannot stream an invalid URL."] = r"網址無效，無法串流。"

# ---------------------------------------------------------------- search
T[r"Search a supported service and select from results to add to queue.\nService and number arguments can be omitted, default number is 3 results.\nSelect from these services:\n- yt, youtube (default)\n- sc, soundcloud\n- yh, yahoo\n- gv, google\n- nv, nico\n- bb, bili\n"] = r"在支援的服務上搜尋，再從結果裡挑一首加進隊列。\n服務與數量參數都可以省略，預設是 3 筆結果。\n可用的服務：\n- yt、youtube（預設）\n- sc、soundcloud\n- yh、yahoo\n- gv、google\n- nv、nico\n- bb、bili\n"
T[r"Please specify a search query.  Use `help search` for more information."] = r"請輸入要搜尋的關鍵字。用 `help search` 看更多說明。"
T[r"You cannot search for more than %(max)s videos"] = r"一次最多只能搜尋 %(max)s 部影片"
T[r"Searching for videos..."] = r"搜尋中…"
T[r"Search failed due to an error: %(error)s"] = r"搜尋失敗，發生錯誤：%(error)s"
T[r"No videos found."] = r"找不到任何影片。"
T[r"To select a song, type the corresponding number."] = r"想選哪一首就輸入對應的號碼。"
T[r"Search results from %(service)s:"] = r"來自 %(service)s 的搜尋結果："
T[r"**%(index)s**. **%(track)s** | %(length)s"] = r"**%(index)s**. **%(track)s** | %(length)s"
T[r"\n**0**. Cancel"] = r"\n**0**. 取消"
T[r"Pick a song"] = r"挑一首歌"
T[r"Result %(number)s of %(total)s: %(url)s"] = r"第 %(number)s / %(total)s 筆結果：%(url)s"

# ---------------------------------------------------------------- queue
T[r"Display information about the current player queue.\nOptional page number shows later entries in the queue.\n"] = r"顯示目前播放隊列的內容。\n可以加上頁碼來看後面的曲目。\n"
T[r"There are no songs queued. Play something with a play command."] = r"隊列裡沒有歌，用 play 指令點一首吧。"
T[r"There are no songs queued! Queue something with a play command."] = r"隊列裡沒有歌！用 play 指令點一首吧。"
T[r"The queue is empty. Add some songs with a play command!"] = r"隊列是空的，用 play 指令加幾首歌吧！"
T[r"Queue page argument must be a whole number."] = r"頁碼必須是整數。"
T[r"Requested page number is out of bounds.\nThere are **%(total)s** pages."] = r"頁碼超出範圍，總共只有 **%(total)s** 頁。"
T[r"(unknown duration)"] = r"（長度未知）"
T[r"Currently playing: `%(title)s`\nAdded by: `%(user)s`\nProgress: `[%(progress)s/%(total)s]`\n"] = r"正在播放：`%(title)s`\n點播者：`%(user)s`\n進度：`[%(progress)s/%(total)s]`\n"
T[r"%(progress)sThere are `%(total)s` entries in the queue.\nHere are the next %(per_page)s songs, starting at song #%(start)s\n\n%(tracks)s"] = r"%(progress)s隊列裡共有 `%(total)s` 首。\n以下是接下來的 %(per_page)s 首，從第 #%(start)s 首開始\n\n%(tracks)s"
T[r"Songs in queue"] = r"隊列中的歌曲"
T[r"**Entry #%(index)s:**Title: `%(title)s`\nAdded by: `%(user)s`\n\n"] = r"**第 %(index)s 首：**標題：`%(title)s`\n點播者：`%(user)s`\n\n"
T[r"Try that again. MusicBot couldn't make or get a reference to the queue message.\nIf the issue persists, file a bug report."] = r"再試一次。MusicBot 抓不到隊列訊息的參照。\n如果一直這樣，請回報 bug。"
T[r"Shuffle all current tracks in the queue."] = r"把隊列裡所有曲目打亂。"
T[r"Shuffled all songs in the queue."] = r"已把隊列裡的歌全部打亂。"
T[r"Removes all songs currently in the queue."] = r"清空隊列裡所有的歌。"
T[r"Cleared all songs from the queue."] = r"已清空隊列。"

# ---------------------------------------------------------------- move / remove
T[r"    Move song at position FROM to position TO.\n"] = r"    把第 FROM 位的歌移動到第 TO 位。\n"
T[r"Swap existing songs in the queue using their position numbers.\nUse the queue command to find track position numbers.\n"] = r"用位置編號來調換隊列裡的歌。\n用 queue 指令可以查到每首歌的位置編號。\n"
T[r"Song positions must be integers!"] = r"位置編號必須是整數！"
T[r"You gave a position outside the playlist size!"] = r"你給的位置超出隊列長度！"
T[r"Successfully moved song from position %(from)s in queue to position %(to)s!"] = r"已把歌曲從第 %(from)s 位移到第 %(to)s 位！"
T[r"    Remove a song at the end of the queue or at [POSITION].\n"] = r"    移除隊列最後一首，或第 [POSITION] 位的歌。\n"
T[r"    Remove songs from position FROM to position TO.\n"] = r"    移除第 FROM 位到第 TO 位之間的歌。\n"
T[r"    Remove songs added by the mentioned user.\n"] = r"    移除被標註的使用者所點的歌。\n"
T[r"Nothing in the queue to remove!"] = r"隊列裡沒有東西可以移除！"
T[r"Invalid positions. Use the queue command to find queue positions."] = r"位置無效。用 queue 指令查詢隊列位置。"
T[r"Invalid entry number. Use the queue command to find queue positions."] = r"曲目編號無效。用 queue 指令查詢隊列位置。"
T[r"You do not have the permission to remove all the songs in the given range from the queue.\n"] = r"你沒有權限移除這個範圍內的所有歌曲。\n"
T[r"Successfully removed songs %(from)s through %(to)s!"] = r"已移除第 %(from)s 到第 %(to)s 首！"
T[r"Removed `%(track)s` added by `%(user)s`"] = r"已移除 `%(user)s` 點的 `%(track)s`"
T[r"Nothing found in the queue from user `%(user)s`"] = r"隊列裡找不到 `%(user)s` 點的歌"
T[r"You do not have the permission to remove that entry from the queue.\nYou must be the one who queued it or have instant skip permissions."] = r"你沒有權限移除這首歌。\n必須是你自己點的，或是擁有直接跳過的權限。"
T[r"Removed entry `%(track)s` added by `%(user)s`"] = r"已移除 `%(user)s` 點的 `%(track)s`"
T[r"Removed entry `%(track)s`"] = r"已移除 `%(track)s`"

# ---------------------------------------------------------------- skip
T[r"Skip or vote to skip the current playing song.\nMembers with InstaSkip permission may use force parameter to bypass voting.\nIf LegacySkip option is enabled, the force parameter can be ignored.\n"] = r"跳過目前這首歌，或投票跳過。\n擁有 InstaSkip 權限的成員可以用 force 參數直接跳過、不必投票。\n如果有開 LegacySkip 選項，force 參數可以省略。\n"
T[r"Can't skip! The player is not playing!"] = r"沒辦法跳過！播放器根本沒在播！"
T[r"The next song `%(track)s` is downloading, please wait."] = r"下一首 `%(track)s` 正在下載，請稍候。"
T[r"The next song will be played shortly. Please wait."] = r"下一首馬上就會播，請稍候。"
T[r"Something odd is happening.\nYou might want to restart the bot if it doesn't start working."] = r"有點怪怪的。\n如果一直沒反應，可以考慮重啟機器人。"
T[r"Something strange is happening.\nYou might want to restart the bot if it doesn't start working."] = r"有點不對勁。\n如果一直沒反應，可以考慮重啟機器人。"
T[r"You do not have permission to force skip a looped song."] = r"你沒有權限強制跳過單曲循環中的歌。"
T[r"Force skipped `%(track)s`."] = r"已強制跳過 `%(track)s`。"
T[r"You do not have permission to force skip."] = r"你沒有強制跳過的權限。"
T[r"You do not have permission to skip a looped song."] = r"你沒有權限跳過單曲循環中的歌。"
T[r"Your skip for `%(track)s` was acknowledged.\nThe vote to skip has been passed.%(next_up)s"] = r"已收到你對 `%(track)s` 的跳過票。\n跳過投票通過了。%(next_up)s"
T[r" Next song coming up!"] = r" 下一首來囉！"
T[r"Your skip for `%(track)s` was acknowledged.\nNeed **%(votes)s** more vote(s) to skip this song."] = r"已收到你對 `%(track)s` 的跳過票。\n還需要 **%(votes)s** 票才能跳過這首。"

# ---------------------------------------------------------------- pause / resume / seek / repeat / speed
T[r"Pause playback if a track is currently playing."] = r"如果正在播放，就暫停。"
T[r"Paused music in `%(channel)s`"] = r"已在 `%(channel)s` 暫停播放"
T[r"Player is not playing."] = r"播放器沒有在播放。"
T[r"Resumes playback if the player was previously paused."] = r"如果先前是暫停狀態，就繼續播放。"
T[r"Resumed music in `%(channel)s`"] = r"已在 `%(channel)s` 繼續播放"
T[r"Resumed music queue"] = r"已繼續播放隊列"
T[r"Player is not paused."] = r"播放器不是暫停狀態。"
T[r"Restarts the current song at the given time.\nIf time starts with + or - seek will be relative to current playback time.\nTime should be given in seconds, fractional seconds are accepted.\nDue to codec specifics in ffmpeg, this may not be accurate.\n"] = r"把目前這首歌跳到指定時間點重新播放。\n時間前面加 + 或 - 就是相對於目前播放位置。\n時間以秒為單位，可以有小數。\n受 ffmpeg 編解碼特性影響，可能不會非常精準。\n"
T[r"Cannot use seek if there is nothing playing."] = r"沒有在播東西，不能用 seek。"
T[r"Cannot use seek on current track, it has an unknown duration."] = r"這首歌長度未知，不能用 seek。"
T[r"Seeking is not supported for streams."] = r"串流不支援 seek。"
T[r"Cannot use seek without a time to position playback."] = r"用 seek 必須指定要跳到的時間。"
T[r"Could not convert `%(input)s` to a valid time in seconds."] = r"`%(input)s` 無法轉換成有效的秒數。"
T[r"Cannot seek to `%(input)s` (`%(seconds)s` seconds) in the current track with a length of `%(progress)s / %(total)s`"] = r"無法跳到 `%(input)s`（`%(seconds)s` 秒），目前這首的長度是 `%(progress)s / %(total)s`"
T[r"Seeking to time `%(input)s` (`%(seconds).2f` seconds) in the current song."] = r"跳到 `%(input)s`（`%(seconds).2f` 秒）。"
T[r"Toggles playlist or song looping.\nIf no option is provided the current song will be repeated.\nIf no option is provided and the song is already repeating, repeating will be turned off.\n"] = r"切換整個隊列或單曲的循環播放。\n不給參數的話就是重複目前這首。\n不給參數且已經在重複時，就會關掉循環。\n"
T[r"Invalid sub-command. Use the command `help repeat` for usage examples."] = r"子指令無效。用 `help repeat` 看用法範例。"
T[r"Playlist is now repeating."] = r"隊列開始循環播放。"
T[r"Playlist is no longer repeating."] = r"隊列已停止循環播放。"
T[r"Player will now loop the current song."] = r"開始單曲循環。"
T[r"Player will no longer loop the current song."] = r"已關閉單曲循環。"
T[r"Player is already looping a song!"] = r"已經在單曲循環了！"
T[r"The player is not currently looping."] = r"播放器目前沒有在循環。"
T[r"Song is no longer repeating."] = r"這首歌已停止重複。"
T[r"Song is now repeating."] = r"這首歌開始重複。"
T[r"Set the output volume level of MusicBot from 1 to 100.\nVolume parameter allows a leading + or - for relative adjustments.\nThe volume setting is retained until MusicBot is restarted.\n"] = r"設定 MusicBot 的輸出音量，範圍 1 到 100。\n數值前面加 + 或 - 就是相對調整。\n這個設定會保留到 MusicBot 重啟為止。\n"
T[r"Current volume: `%(volume)s%%`"] = r"目前音量：`%(volume)s%%`"
T[r"`%(new_volume)s` is not a valid number"] = r"`%(new_volume)s` 不是有效的數字"
T[r"Updated volume from **%(old)d** to **%(new)d**"] = r"音量已從 **%(old)d** 調整為 **%(new)d**"
T[r"Unreasonable volume change provided: %(old_volume)s%(adjustment)s is %(new_volume)s.\nVolume can only be set from 1 to 100."] = r"音量調整幅度不合理：%(old_volume)s%(adjustment)s 會變成 %(new_volume)s。\n音量只能設在 1 到 100 之間。"
T[r"Unreasonable volume provided: %(volume)s. Provide a value between 1 and 100."] = r"音量數值不合理：%(volume)s，請給 1 到 100 之間的值。"
T[r"Change the playback speed of the currently playing track only.\nThe rate must be between 0.5 and 100.0 due to ffmpeg limits.\nStreaming playback does not support speed adjustments.\n"] = r"只調整目前這首歌的播放速度。\n受 ffmpeg 限制，倍率必須在 0.5 到 100.0 之間。\n串流播放不支援調速。\n"
T[r"No track is playing, cannot set speed.\nUse the config command to set a default playback speed."] = r"沒有在播歌，無法設定速度。\n要設定預設播放速度請用 config 指令。"
T[r"Speed cannot be applied to streamed media."] = r"串流媒體無法調整速度。"
T[r"You must provide a speed to set."] = r"必須指定要設定的速度。"
T[r"The speed you provided is invalid. Use a number between 0.5 and 100."] = r"速度數值無效，請給 0.5 到 100 之間的數字。"
T[r"Setting playback speed to `%(speed).3f` for current track."] = r"已把目前這首的播放速度設為 `%(speed).3f`。"

# ---------------------------------------------------------------- karaoke / follow / prefix
T[r"Toggle karaoke mode on or off. While enabled, only karaoke members may queue songs.\nGroups with BypassKaraokeMode permission control which members are Karaoke members.\n"] = r"開啟或關閉卡拉 OK 模式。開啟時只有卡拉 OK 成員可以點歌。\n擁有 BypassKaraokeMode 權限的群組決定誰算是卡拉 OK 成員。\n"
T[r"Karaoke mode is enabled, please try again when its disabled!"] = r"卡拉 OK 模式開著，等關掉再試一次！"
T[r"Makes MusicBot follow a user when they change channels in a server.\n"] = r"讓 MusicBot 跟著某位使用者在伺服器裡換頻道。\n"
T[r"No longer following user `%(user)s`"] = r"已停止跟隨 `%(user)s`"
T[r"Now following user `%(user)s` between voice channels."] = r"開始跟著 `%(user)s` 在語音頻道之間移動。"
T[r"MusicBot cannot follow a user that is not a member of the server."] = r"MusicBot 無法跟隨不是這個伺服器成員的人。"
T[r"Will follow user `%(user)s` between voice channels."] = r"會跟著 `%(user)s` 在語音頻道之間移動。"
T[r"Custom emoji must be from this server to use as a prefix."] = r"要拿自訂表情符號當前綴，必須是這個伺服器的。"
T[r"Server command prefix is cleared."] = r"已清除本伺服器的指令前綴。"
T[r"Server command prefix is now:  %(prefix)s"] = r"本伺服器的指令前綴現在是：%(prefix)s"

# ---------------------------------------------------------------- help
T[r"Show usage and description of a command, or list all available commands.\n"] = r"顯示某個指令的用法與說明，或列出所有可用指令。\n"
T[r"**Aliases for this command:**\n"] = r"**這個指令的別名：**\n"
T[r"**Alias of command:**\n  `%(command)s`\n"] = r"**此為指令的別名：**\n  `%(command)s`\n"
T[r"No such command"] = r"沒有這個指令"
T[r"The list above shows only commands permitted for your use.\nFor a list of all commands, run: %(example_all)s\n"] = r"以上只列出你有權限使用的指令。\n要看全部指令請執行：%(example_all)s\n"
T[r"**Commands by name:** *(without prefix)*\n```\n%(command_list)s\n```\n**Command Prefix:** %(prefix)s\n\nFor help with a particular command, run: %(example_command)s\n%(all_note)s"] = r"**指令一覽：** *(不含前綴)*\n```\n%(command_list)s\n```\n**指令前綴：** %(prefix)s\n\n要查詢個別指令的用法，請執行：%(example_command)s\n%(all_note)s"
T[r"**Command:** %(name)s"] = r"**指令：** %(name)s"
T[r"**Example with prefix:**\n%(prefix)s`%(command)s ...`\n"] = r"**加上前綴的範例：**\n%(prefix)s`%(command)s ...`\n"
T[r"No description given.\n"] = r"沒有提供說明。\n"
T[r"No usage given."] = r"沒有提供用法。"
T[r"**Example usage:**\n```%(usage)s```\n%(prefix_note)s**Description:**\n%(desc)s"] = r"**用法範例：**\n```%(usage)s```\n%(prefix_note)s**說明：**\n%(desc)s"
T[r"Exception Error"] = r"發生例外錯誤"
T[r"Invalid option for command: `%(option)s`"] = r"指令的選項無效：`%(option)s`"

# ---------------------------------------------------------------- permissions / access
T[r"This command is not allowed for your permissions group:  %(group)s"] = r"你所屬的權限群組 %(group)s 不允許使用這個指令。"
T[r"Only the owner can use this command."] = r"只有擁有者可以使用這個指令。"
T[r"Only dev users can use this command."] = r"只有開發者可以使用這個指令。"
T[r"Get a list of your permissions, or the permissions of the mentioned user."] = r"查看你自己、或被標註的使用者的權限。"
T[r"Your command permissions in %(server)s are:\n```\n%(permissions)s\n```"] = r"你在 %(server)s 的指令權限是：\n```\n%(permissions)s\n```"
T[r"The command permissions for %(username)s in %(server)s are:\n```\n%(permissions)s\n```"] = r"%(username)s 在 %(server)s 的指令權限是：\n```\n%(permissions)s\n```"
T[r"Invalid user ID or server nickname, please double-check the ID and try again."] = r"使用者 ID 或伺服器暱稱無效，請再確認一次。"
T[r"Could not determine the discord User.  Try again."] = r"無法辨識這位 Discord 使用者，請再試一次。"
T[r"You must mention a user or provide their ID number."] = r"你必須標註一位使用者，或提供他的 ID。"
T[r"MusicBot could not find the user(s) you specified."] = r"MusicBot 找不到你指定的使用者。"
T[r"You do not have permission to play the requested media.\nThe yt-dlp extractor `%(extractor)s` is not permitted in your group."] = r"你沒有權限播放這個來源。\n你所屬群組不允許使用 yt-dlp 的 `%(extractor)s` 擷取器。"

# ---------------------------------------------------------------- download / extraction errors
T[r"Song info extraction returned no data."] = r"擷取歌曲資訊時沒有拿到任何資料。"
T[r"Cannot continue extraction, event loop is closed."] = r"無法繼續擷取，事件迴圈已關閉。"
T[r"Spotify URL is invalid or not supported."] = r"Spotify 網址無效或不支援。"
T[r"The local media file could not be found."] = r"找不到這個本機媒體檔案。"
T[r"Cannot download Spotify links, processing error with type: %(type)s"] = r"無法下載 Spotify 連結，處理時發生型別錯誤：%(type)s"
T[r"Download did not complete due to an error: %(raw_error)s"] = r"下載未完成，發生錯誤：%(raw_error)s"
T[r"Download failed due to a yt-dlp error: %(raw_error)s"] = r"下載失敗，yt-dlp 發生錯誤：%(raw_error)s"
T[r"Download failed due to an unhandled exception: %(raw_error)s"] = r"下載失敗，發生未處理的例外：%(raw_error)s"
T[r"Failed to extract data for the requested media."] = r"無法擷取這個媒體的資料。"
T[r"Error in yt-dlp while downloading media data: %(raw_error)s"] = r"yt-dlp 下載媒體資料時發生錯誤：%(raw_error)s"
T[r"Error in yt-dlp while downloading stream data: %(raw_error)s"] = r"yt-dlp 下載串流資料時發生錯誤：%(raw_error)s"
T[r"The playlist does not exist."] = r"這個播放清單不存在。"
T[r"Could not extract information"] = r"無法擷取資訊"
T[r"This is a playlist."] = r"這是一個播放清單。"
T[r"Invalid content type `%(type)s` for URL: %(url)s"] = r"網址 %(url)s 的內容類型 `%(type)s` 無效"
T[r"no duration data"] = r"沒有長度資料"
T[r"no duration data in current entry"] = r"目前這首沒有長度資料"
T[r"Unknown"] = r"未知"
T[r"Failed to get a guest token from Spotify, please try specifying client ID and client secret"] = r"無法從 Spotify 取得訪客權杖，請改用自己的 client ID 與 client secret"

# ---------------------------------------------------------------- misc user-facing
T[r"Unlimited"] = r"無限制"
T[r"Disabled"] = r"已停用"
T[r"Enabled"] = r"已啟用"
T[r"%(time)s days"] = r"%(time)s 天"
T[r"Generate an invite link that can be used to add this bot to another server."] = r"產生一個邀請連結，可以把這個機器人加到其他伺服器。"
T[r"Click here to add me to a discord server:\n%(url)s"] = r"點這裡把我加進 Discord 伺服器：\n%(url)s"
T[r"Displays the MusicBot uptime, or time since last start / restart."] = r"顯示 MusicBot 的運行時間（距離上次啟動或重啟多久）。"
T[r"%(name)s has been online for `%(time)s`"] = r"%(name)s 已經上線 `%(time)s`"
T[r"Display MusicBot version number in the chat."] = r"在聊天室顯示 MusicBot 的版本號。"
T[r"Display latency information for Discord API and all connected voice clients."] = r"顯示 Discord API 與所有語音連線的延遲資訊。"
T[r"Display API latency and Voice latency if MusicBot is connected."] = r"顯示 API 延遲，以及 MusicBot 已連線時的語音延遲。"
T[r"No voice clients connected.\n"] = r"沒有任何語音連線。\n"
T[r"**API Latency:** `%(delay).0f ms`%(voice)s"] = r"**API 延遲：** `%(delay).0f ms`%(voice)s"
T[r"Display your Discord User ID, or the ID of a mentioned user.\nThis command is deprecated in favor of Developer Mode in Discord clients.\n"] = r"顯示你的 Discord 使用者 ID，或被標註者的 ID。\n這個指令已不建議使用，請改用 Discord 用戶端的開發者模式。\n"
T[r"Your user ID is `%(id)s`"] = r"你的使用者 ID 是 `%(id)s`"
T[r"The user ID for `%(username)s` is `%(id)s`"] = r"`%(username)s` 的使用者 ID 是 `%(id)s`"
T[r"Search for and remove bot messages and commands from the calling text channel.\nOptionally supply a number of messages to search through, 50 by default 500 max.\nThis command may be slow if larger ranges are given.\n"] = r"在目前的文字頻道裡搜尋並刪除機器人的訊息與指令。\n可以指定要往回搜尋幾則訊息，預設 50、最多 500。\n範圍給太大時這個指令會比較慢。\n"
T[r"Invalid parameter. Please provide a number of messages to search."] = r"參數無效，請提供要搜尋的訊息數量。"
T[r"Cannot use purge on private DM channel."] = r"私訊頻道不能用 purge。"
T[r"Cleaned up %(number)s message(s)."] = r"已清除 %(number)s 則訊息。"
T[r"Bot does not have permission to manage messages."] = r"機器人沒有管理訊息的權限。"
T[r"Display information about cache storage or clear cache according to configured limits.\nUsing update option will scan the cache for external changes before displaying details."] = r"顯示快取儲存資訊，或依設定的上限清除快取。\n加上 update 選項會先掃描快取的外部變動再顯示細節。"
T[r"Invalid option specified, use: info, update, or clear"] = r"選項無效，可用的有：info、update、clear"
T[r"Cache has been cleared."] = r"快取已清除。"
T[r"**Failed** to delete cache, check logs for more info..."] = r"清除快取**失敗**，詳情請看日誌…"
T[r"No cache found to clear."] = r"沒有找到可以清除的快取。"
T[r"Dump the individual URLs of a playlist to a file."] = r"把播放清單裡每一首的網址匯出成檔案。"
T[r"The given URL was not a valid URL."] = r"提供的網址無效。"
T[r"Could not extract info from input url\n%(raw_error)s\n"] = r"無法從輸入的網址擷取資訊\n%(raw_error)s\n"
T[r"This does not seem to be a playlist."] = r"這看起來不是一個播放清單。"
T[r"Here is the playlist dump for:  %(url)s"] = r"這是 %(url)s 的播放清單匯出："
T[r"Manage the language used for messages in the calling server."] = r"管理本伺服器所使用的訊息語言。"
T[r"    Show language codes available to use.\n"] = r"    列出可用的語言代碼。\n"
T[r"    Set the desired language for this server.\n"] = r"    設定本伺服器要用的語言。\n"
T[r"    Reset the server language to bot's default language.\n"] = r"    把本伺服器的語言重設為機器人的預設語言。\n"
T[r"This command can only be used in guilds."] = r"這個指令只能在伺服器裡使用。"
T[r"Invalid sub-command given. Use the help command for more information."] = r"子指令無效，用 help 指令看更多說明。"
T[r"**Current Language:** `%(locale)s`\n**Available Languages:**\n```\n%(languages)s```"] = r"**目前語言：** `%(locale)s`\n**可用語言：**\n```\n%(languages)s```"
T[r"Cannot set language to `%(locale)s` it is not available."] = r"無法把語言設為 `%(locale)s`，這個語言不可用。"
T[r"Language for this server now set to: `%(locale)s`"] = r"本伺服器的語言已設定為：`%(locale)s`"
T[r"Language for this server has been reset to: `%(locale)s`"] = r"本伺服器的語言已重設為：`%(locale)s`"

# ---------------------------------------------------------------- autoplaylist (visible to users)
T[r"Manage auto playlist files and per-guild settings.\nAuto playlists use their own queue, only playing when the main queue is empty."] = r"管理自動播放清單檔案與各伺服器的設定。\n自動播放清單有自己的隊列，只有在主隊列空了才會播。"
T[r"All songs in the queue are already in the autoplaylist."] = r"隊列裡的歌全部都已經在自動播放清單裡了。"
T[r"Added %(number)d songs to the autoplaylist."] = r"已加入 %(number)d 首歌到自動播放清單。"
T[r"Added `%(url)s` to the autoplaylist."] = r"已把 `%(url)s` 加進自動播放清單。"
T[r"This song is already in the autoplaylist."] = r"這首歌已經在自動播放清單裡了。"
T[r"Removed `%(url)s` from the autoplaylist."] = r"已把 `%(url)s` 從自動播放清單移除。"
T[r"This song is not yet in the autoplaylist."] = r"這首歌還不在自動播放清單裡。"
T[r"Loaded a fresh copy of the playlist: `%(file)s`"] = r"已重新載入播放清單：`%(file)s`"
T[r"You must provide a playlist filename."] = r"必須提供播放清單的檔名。"
T[r"The playlist for this server has been updated to: `%(name)s`%(note)s"] = r"本伺服器的播放清單已更新為：`%(name)s`%(note)s"
T[r"**Current Playlist:** `%(playlist)s`**Available Playlists:**\n%(names)s"] = r"**目前的播放清單：** `%(playlist)s`**可用的播放清單：**\n%(names)s"
T[r"No playlist file exists with the name: `%(playlist)s`"] = r"找不到名為 `%(playlist)s` 的播放清單檔案"
T[r"The playlist `%(playlist)s` has been cleared."] = r"播放清單 `%(playlist)s` 已清空。"
T[r"The tracks in playlist `%(playlist)s` will be added to the queue.\nPlease wait while MusicBot processes the playlist."] = r"播放清單 `%(playlist)s` 裡的曲目將被加進隊列。\nMusicBot 處理中，請稍候。"
T[r"Added %(number)d track(s) to the queue from playlist `%(playlist)s`"] = r"已從播放清單 `%(playlist)s` 加入 %(number)d 首歌到隊列"
T[r"The playlist has been reloaded from disk."] = r"播放清單已從磁碟重新載入。"

# ---------------------------------------------------------------- block lists (mod-facing but short)
T[r"User block list is currently enabled."] = r"使用者封鎖清單目前為啟用。"
T[r"User block list is currently disabled."] = r"使用者封鎖清單目前為停用。"
T[r"The owner cannot be added to the block list."] = r"擁有者不能被加入封鎖清單。"
T[r"Cannot add the users you listed, they are already added."] = r"無法加入你列出的使用者，他們已經在清單裡了。"
T[r"%(number)s user(s) have been added to the block list.\n%(status)s"] = r"已將 %(number)s 位使用者加入封鎖清單。\n%(status)s"
T[r"%(number)s user(s) have been removed from the block list.\n%(status)s"] = r"已將 %(number)s 位使用者從封鎖清單移除。\n%(status)s"
T[r"User: `%(user)s` is not blocked.\n"] = r"使用者 `%(user)s` 未被封鎖。\n"
T[r"User: `%(user)s` is blocked.\n"] = r"使用者 `%(user)s` 已被封鎖。\n"
T[r"**Block list status:**\n%(status)s\n%(users)s"] = r"**封鎖清單狀態：**\n%(status)s\n%(users)s"
T[r"Subject `%(subject)s` is already in the song block list."] = r"`%(subject)s` 已經在歌曲封鎖清單裡了。"
T[r"Added subject `%(subject)s` to the song block list.\n%(status)s"] = r"已把 `%(subject)s` 加進歌曲封鎖清單。\n%(status)s"
T[r"The subject is not in the song block list and cannot be removed."] = r"這個項目不在歌曲封鎖清單裡，無法移除。"
T[r"Subject `%(subject)s` has been removed from the block list.\n%(status)s"] = r"已把 `%(subject)s` 從封鎖清單移除。\n%(status)s"
T[r"You must provide a song subject if no song is currently playing."] = r"目前沒有在播歌，必須指定要封鎖的對象。"

# =====================================================================================

HEADER = '''msgid ""
msgstr ""
"Project-Id-Version: MusicBot\\n"
"Report-Msgid-Bugs-To: \\n"
"POT-Creation-Date: 2026-08-04 05:00+0800\\n"
"PO-Revision-Date: 2026-08-04 05:00+0800\\n"
"Last-Translator: chy1211\\n"
"Language-Team: Traditional Chinese\\n"
"Language: zh_TW\\n"
"MIME-Version: 1.0\\n"
"Content-Type: text/plain; charset=UTF-8\\n"
"Content-Transfer-Encoding: 8bit\\n"
"Plural-Forms: nplurals=1; plural=0;\\n"
'''


def main():
    ref = pathlib.Path(sys.argv[1])
    out = pathlib.Path(sys.argv[2])

    text = ref.read_text(encoding="utf-8")
    entries = re.split(r"\n\n+", text)

    seen = set()
    used = set()
    lines = [HEADER]
    n_total = 0
    n_trans = 0

    for e in entries:
        if "msgid " not in e:
            continue
        m = re.search(r"^msgid ((?:\s*\"(?:[^\"\\]|\\.)*\"\n?)+)", e, re.M)
        if not m:
            continue
        parts = re.findall(r"\"((?:[^\"\\]|\\.)*)\"", m.group(1))
        msgid = "".join(parts)
        if not msgid or msgid in seen:
            continue
        seen.add(msgid)
        n_total += 1

        refs = re.findall(r"^#: (.+)$", e, re.M)
        msgstr = T.get(msgid, "")
        if msgstr:
            n_trans += 1
            used.add(msgid)

        for r in refs:
            lines.append(f"#: {r}")
        lines.append(f'msgid "{msgid}"')
        lines.append(f'msgstr "{msgstr}"')
        lines.append("")

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")

    unmatched = sorted(set(T) - used)
    print(f"catalog entries : {n_total}")
    print(f"translated      : {n_trans}")
    print(f"coverage        : {n_trans * 100 // n_total}%")
    print(f"wrote           : {out}")
    if unmatched:
        print(f"\n!! UNMATCHED KEYS ({len(unmatched)}) -- these did NOT match any msgid:")
        for u in unmatched:
            print(f"   {u[:100]}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
