import os, json, time, random, secrets, string, sqlite3, asyncio, logging
from contextlib import contextmanager
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup, KeyboardButton
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, ContextTypes, filters
TOKEN=os.getenv('BOT_TOKEN','').strip(); ADMIN_ID=int(os.getenv('ADMIN_ID','0') or 0); DB_PATH=os.getenv('DB_PATH','/data/bazichi.db'); MAX=10; SECONDS=25
logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(name)s: %(message)s'); log=logging.getLogger('bazichi'); TASKS={}
MENU=ReplyKeyboardMarkup([[KeyboardButton('🎮 شروع بازی'),KeyboardButton('🌍 مسابقه عمومی')],[KeyboardButton('🔐 ساخت اتاق خصوصی'),KeyboardButton('🚪 ورود با کد دعوت')],[KeyboardButton('👤 پروفایل من'),KeyboardButton('🏆 جدول رتبه‌بندی')],[KeyboardButton('📜 تاریخچه بازی‌ها'),KeyboardButton('📖 راهنما')]],resize_keyboard=True)
GAMES={'quiz':'🧠 اطلاعات عمومی','word':'🔤 حدس کلمه','riddle':'❓ معما و چیستان','truth':'🎭 جرئت یا حقیقت','number':'🔢 حدس عدد','speed':'⚡ سرعت و پاسخ سریع'}
SEED=[('quiz','عمومی','آسان','پایتخت ایران کدام شهر است؟',['تهران','اصفهان','شیراز','تبریز'],0),('quiz','علوم','آسان','کدام سیاره به سیاره سرخ معروف است؟',['زهره','مریخ','مشتری','عطارد'],1),('quiz','علوم','متوسط','نماد شیمیایی طلا چیست؟',['Ag','Fe','Au','O'],2),('quiz','جغرافیا','آسان','بزرگ‌ترین اقیانوس جهان کدام است؟',['اطلس','هند','منجمد شمالی','آرام'],3),('riddle','چیستان','آسان','آن چیست که هرچه از آن برداری بزرگ‌تر می‌شود؟',['گودال','آب','آتش','سایه'],0),('riddle','چیستان','متوسط','چه چیزی دندان دارد اما غذا نمی‌خورد؟',['شانه','چنگال','اره','زیپ'],0),('word','واژگان','آسان','حروف به‌هم‌ریخته را مرتب کن: «ب،ا،ت،ک»',['کتاب','باتک','کباب','تابک'],0),('speed','عمومی','آسان','حاصل ۷ × ۸ چند است؟',['۵۴','۵۶','۶۴','۴۸'],1),('speed','عمومی','آسان','کدام عدد زوج است؟',['۱۳','۱۷','۲۲','۳۱'],2)]
TRUTHS=['یک خاطره خنده‌دار از مدرسه تعریف کن.','اگر یک مهارت را فوری یاد می‌گرفتی، چه بود؟','سه ویژگی خوب خودت را بگو.']; DARES=['تا دور بعد فقط با یک کلمه جواب بده.','یک جمله انگیزشی بنویس.','اسم سه میوه را در پنج ثانیه بنویس.']
@contextmanager
def db():
 os.makedirs(os.path.dirname(DB_PATH) or '.',exist_ok=True); c=sqlite3.connect(DB_PATH,timeout=30); c.row_factory=sqlite3.Row; c.execute('PRAGMA journal_mode=WAL'); c.execute('PRAGMA foreign_keys=ON')
 try: yield c; c.commit()
 except: c.rollback(); raise
 finally: c.close()
def init_db():
 with db() as c:
  c.executescript('''CREATE TABLE IF NOT EXISTS users(user_id INTEGER PRIMARY KEY,username TEXT,full_name TEXT,total_points INTEGER DEFAULT 0,games INTEGER DEFAULT 0,wins INTEGER DEFAULT 0,losses INTEGER DEFAULT 0,level INTEGER DEFAULT 1,blocked INTEGER DEFAULT 0,joined_at TEXT DEFAULT CURRENT_TIMESTAMP,last_seen TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE TABLE IF NOT EXISTS matches(id INTEGER PRIMARY KEY AUTOINCREMENT,code TEXT UNIQUE,kind TEXT,host_id INTEGER,status TEXT,game_type TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,started_at TEXT,ended_at TEXT);
  CREATE TABLE IF NOT EXISTS players(match_id INTEGER,user_id INTEGER,score INTEGER DEFAULT 0,joined_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(match_id,user_id),FOREIGN KEY(match_id) REFERENCES matches(id) ON DELETE CASCADE);
  CREATE TABLE IF NOT EXISTS questions(id INTEGER PRIMARY KEY AUTOINCREMENT,game_type TEXT,category TEXT,difficulty TEXT,prompt TEXT,options TEXT,answer INTEGER,active INTEGER DEFAULT 1);
  CREATE TABLE IF NOT EXISTS rounds(id INTEGER PRIMARY KEY AUTOINCREMENT,match_id INTEGER,round_no INTEGER,game_type TEXT,prompt TEXT,options TEXT,answer INTEGER,extra TEXT,deadline REAL,status TEXT DEFAULT 'open',UNIQUE(match_id,round_no));
  CREATE TABLE IF NOT EXISTS answers(round_id INTEGER,user_id INTEGER,answer TEXT,correct INTEGER DEFAULT 0,points INTEGER DEFAULT 0,answered_at TEXT DEFAULT CURRENT_TIMESTAMP,PRIMARY KEY(round_id,user_id));
  CREATE TABLE IF NOT EXISTS reports(id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER,match_id INTEGER,reason TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP,status TEXT DEFAULT 'new');
  CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT,level TEXT,message TEXT,created_at TEXT DEFAULT CURRENT_TIMESTAMP);
  CREATE INDEX IF NOT EXISTS idx_match_status ON matches(status); CREATE INDEX IF NOT EXISTS idx_player_user ON players(user_id);''')
  if c.execute('SELECT COUNT(*) n FROM questions').fetchone()['n']==0: c.executemany('INSERT INTO questions(game_type,category,difficulty,prompt,options,answer) VALUES(?,?,?,?,?,?)',[(g,ca,d,p,json.dumps(o,ensure_ascii=False),a) for g,ca,d,p,o,a in SEED])
def event(level,msg):
 log.log(getattr(logging,level.upper(),logging.INFO),msg)
 try:
  with db() as c:c.execute('INSERT INTO events(level,message) VALUES(?,?)',(level,msg[:1000]))
 except Exception:log.exception('event log failure')
def upsert(u):
 name=' '.join(x for x in [u.first_name,u.last_name] if x) or 'بازیکن'
 with db() as c:
  c.execute('INSERT INTO users(user_id,username,full_name) VALUES(?,?,?) ON CONFLICT(user_id) DO UPDATE SET username=excluded.username,full_name=excluded.full_name,last_seen=CURRENT_TIMESTAMP',(u.id,u.username,name)); return bool(c.execute('SELECT blocked FROM users WHERE user_id=?',(u.id,)).fetchone()['blocked'])
def active(uid):
 with db() as c:
  r=c.execute("SELECT m.* FROM matches m JOIN players p ON p.match_id=m.id WHERE p.user_id=? AND m.status IN ('waiting','selecting','running') LIMIT 1",(uid,)).fetchone(); return dict(r) if r else None
def players(mid):
 with db() as c:return [dict(x) for x in c.execute('SELECT u.user_id,u.full_name,u.username,p.score FROM players p JOIN users u ON u.user_id=p.user_id WHERE p.match_id=? ORDER BY p.joined_at',(mid,))]
async def send(ctx,uid,msg,**kw):
 try:return await ctx.bot.send_message(chat_id=uid,text=msg,**kw)
 except Exception as e:event('warning',f'DM {uid}: {e}');return None
async def announce(ctx,mid,msg):
 for p in players(mid):await send(ctx,p['user_id'],msg)
async def start(update:Update,ctx:ContextTypes.DEFAULT_TYPE):
 if update.effective_chat.type!='private':return await update.message.reply_text('برای بازی، ابتدا در گفت‌وگوی خصوصی ربات /start را بزنید.')
 if upsert(update.effective_user):return await update.message.reply_text('⛔ دسترسی شما مسدود است.')
 await update.message.reply_text(f'سلام {update.effective_user.first_name or "دوست من"}! 🎉\nبه بازی‌چی خوش آمدی. همه مسابقات رایگان‌اند.',reply_markup=MENU)
async def help_cmd(update,ctx):await update.message.reply_text('📖 راهنما\nبرای بازی خصوصی با ربات /start را بزن. مسابقه عمومی وارد صف می‌شود؛ اتاق خصوصی با کد دعوت ساخته می‌شود. ظرفیت هر مسابقه ۱۰ نفر و حداقل شروع ۲ نفر است. هر دور فقط یک پاسخ ثبت می‌شود. امتیازها صرفاً برای رتبه‌بندی‌اند؛ هیچ پرداخت یا جایزه نقدی وجود ندارد.',reply_markup=MENU)
async def menu(update,ctx):
 t=update.message.text
 if t=='🎮 شروع بازی':await update.message.reply_text('نوع مسابقه را انتخاب کن:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('🌍 عمومی',callback_data='public')],[InlineKeyboardButton('🔐 خصوصی',callback_data='private')]]))
 elif t=='🌍 مسابقه عمومی':await join_public(update,ctx)
 elif t=='🔐 ساخت اتاق خصوصی':await create_private(update,ctx)
 elif t=='🚪 ورود با کد دعوت':ctx.user_data['await']='code';await update.message.reply_text('کد دعوت را بفرست:')
 elif t=='👤 پروفایل من':await profile(update,ctx)
 elif t=='🏆 جدول رتبه‌بندی':await leaderboard(update,ctx)
 elif t=='📜 تاریخچه بازی‌ها':await history(update,ctx)
 elif t=='📖 راهنما':await help_cmd(update,ctx)
async def join_public(update,ctx):
 uid=update.effective_user.id
 if active(uid):return await update.message.reply_text('شما در یک مسابقه فعال هستید.')
 with db() as c:
  r=c.execute("SELECT id FROM matches WHERE kind='public' AND status='waiting' AND (SELECT COUNT(*) FROM players WHERE match_id=matches.id)<10 ORDER BY id LIMIT 1").fetchone()
  if r:mid=r['id']
  else:mid=c.execute("INSERT INTO matches(kind,host_id,status) VALUES('public',?,'waiting')",(uid,)).lastrowid
  c.execute('INSERT OR IGNORE INTO players(match_id,user_id) VALUES(?,?)',(mid,uid)); n=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(mid,)).fetchone()['n']
 await update.message.reply_text(f'🌍 وارد صف شدی. مسابقه #{mid}\nبازیکنان: {n}/10',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('▶️ شروع مسابقه',callback_data=f'start:{mid}')],[InlineKeyboardButton('🚪 خروج',callback_data=f'leave:{mid}')]]))
 await announce(ctx,mid,f'👋 بازیکن جدید به مسابقه #{mid} پیوست؛ ظرفیت {n}/10')
async def create_private(update,ctx):
 uid=update.effective_user.id
 if active(uid):return await update.message.reply_text('ابتدا مسابقه فعال فعلی را ترک کنید.')
 code=''.join(secrets.choice(string.ascii_uppercase+string.digits) for _ in range(6))
 with db() as c:mid=c.execute("INSERT INTO matches(code,kind,host_id,status) VALUES(?,'private',?,'waiting')",(code,uid)).lastrowid;c.execute('INSERT INTO players(match_id,user_id) VALUES(?,?)',(mid,uid))
 await update.message.reply_text(f'🔐 اتاق ساخته شد!\nکد دعوت: `{code}`\nظرفیت: ۱/۱۰',parse_mode=ParseMode.MARKDOWN,reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('▶️ شروع',callback_data=f'start:{mid}')],[InlineKeyboardButton('❌ لغو',callback_data=f'cancel:{mid}')]]))
async def text_router(update,ctx):
 if not update.message or not update.effective_user:return
 if update.effective_chat.type!='private':return await update.message.reply_text('بازی‌ها فقط در گفت‌وگوی خصوصی ربات اجرا می‌شوند.')
 with db() as c:
  registered=c.execute('SELECT blocked FROM users WHERE user_id=?',(update.effective_user.id,)).fetchone()
  if registered:c.execute('UPDATE users SET last_seen=CURRENT_TIMESTAMP WHERE user_id=?',(update.effective_user.id,))
 if not registered:return await update.message.reply_text('ابتدا /start را در گفت‌وگوی خصوصی ربات اجرا کن.')
 if registered['blocked']:return await update.message.reply_text('⛔ دسترسی شما مسدود شده است.')
 if ctx.user_data.get('admin') and await admin_text(update,ctx):return
 if ctx.user_data.get('await')=='code':
  ctx.user_data.pop('await',None);uid=update.effective_user.id
  if active(uid):return await update.message.reply_text('شما در مسابقه فعال هستید.')
  with db() as c:
   m=c.execute("SELECT * FROM matches WHERE code=? AND kind='private' AND status='waiting'",(update.message.text.strip().upper(),)).fetchone()
   if not m:return await update.message.reply_text('کد نامعتبر است یا اتاق بسته شده.')
   n=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(m['id'],)).fetchone()['n']
   if n>=10:return await update.message.reply_text('ظرفیت اتاق تکمیل است.')
   c.execute('INSERT OR IGNORE INTO players(match_id,user_id) VALUES(?,?)',(m['id'],uid));mid=m['id'];n+=1
  await update.message.reply_text(f'✅ وارد اتاق شدی. ظرفیت {n}/10',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('▶️ شروع (میزبان)',callback_data=f'start:{mid}')]]));await announce(ctx,mid,f'یک بازیکن وارد اتاق شد؛ ظرفیت {n}/10');return
 if await game_text(update,ctx):return
 if update.message.text in ['🎮 شروع بازی','🌍 مسابقه عمومی','🔐 ساخت اتاق خصوصی','🚪 ورود با کد دعوت','👤 پروفایل من','🏆 جدول رتبه‌بندی','📜 تاریخچه بازی‌ها','📖 راهنما']:await menu(update,ctx)
 else:await update.message.reply_text('برای نمایش منو /start را بزن.',reply_markup=MENU)
async def callbacks(update,ctx):
 q=update.callback_query;await q.answer();uid=q.from_user.id;d=q.data
 try:
  if d in ('public','private'):
   if d=='public':await q.message.reply_text('از منوی «مسابقه عمومی» وارد صف شو.')
   else:await q.message.reply_text('از منوی «ساخت اتاق خصوصی» اتاق بساز.')
  elif d.startswith('start:'):await start_match(q,ctx,uid,int(d.split(':')[1]))
  elif d.startswith('game:'):
   _,mid,g=d.split(':');await choose_game(q,ctx,uid,int(mid),g)
  elif d.startswith('leave:'):await leave(q,uid,int(d.split(':')[1]))
  elif d.startswith('cancel:'):await cancel(q,ctx,uid,int(d.split(':')[1]))
  elif d.startswith('ans:'):
   _,rid,val=d.split(':');await answer(q,ctx,uid,int(rid),val)
  elif d.startswith('admin:'):await admin_callback(q,ctx,uid,d)
  elif d.startswith('admfinish:'):
   if uid!=ADMIN_ID:return await q.answer('دسترسی ندارید.',show_alert=True)
   await finish(ctx,int(d.split(':')[1]));await q.message.reply_text('مسابقه پایان یافت.')
  elif d.startswith('admcancel:'):
   if uid!=ADMIN_ID:return await q.answer('دسترسی ندارید.',show_alert=True)
   mid=int(d.split(':')[1])
   with db() as c:c.execute("UPDATE matches SET status='cancelled',ended_at=CURRENT_TIMESTAMP WHERE id=? AND status IN ('waiting','selecting','running')",(mid,))
   await announce(ctx,mid,'مسابقه توسط مدیر لغو شد.');await q.message.reply_text('مسابقه لغو شد.')
 except Exception as e:event('error',f'callback {d}: {e}');await q.message.reply_text('خطا رخ داد؛ دوباره تلاش کنید.')
async def start_match(q,ctx,uid,mid):
 with db() as c:
  m=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
  if not m or m['status']!='waiting':return await q.message.reply_text('این مسابقه قابل شروع نیست.')
  if uid not in [p['user_id'] for p in players(mid)]:return await q.message.reply_text('عضو این مسابقه نیستی.')
  if m['host_id']!=uid and uid!=ADMIN_ID:return await q.message.reply_text('فقط میزبان می‌تواند شروع کند.')
  n=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(mid,)).fetchone()['n']
  if n<2:return await q.message.reply_text('حداقل دو بازیکن لازم است.')
  c.execute("UPDATE matches SET status='selecting' WHERE id=?",(mid,))
 await announce(ctx,mid,'🎮 مسابقه آماده است؛ میزبان نوع بازی را انتخاب می‌کند.')
 await send(ctx,m['host_id'],'نوع بازی را انتخاب کن:',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(v,callback_data=f'game:{mid}:{k}')] for k,v in GAMES.items()]))
async def choose_game(q,ctx,uid,mid,g):
 with db() as c:
  m=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
  if not m or m['status']!='selecting' or m['host_id']!=uid:return await q.message.reply_text('انتخاب بازی در دسترس نیست.')
  c.execute("UPDATE matches SET status='running',game_type=? WHERE id=?",(g,mid))
 await announce(ctx,mid,f'🚀 بازی شروع شد: {GAMES[g]}')
 if g=='truth':
  prompt=random.choice(TRUTHS+DARES);await announce(ctx,mid,'🎭 چالش گروهی: '+prompt+'\nمیزبان با /finish مسابقه را پایان دهد.');return
 if g=='number':
  secret=random.randint(1,30)
  with db() as c:c.execute('INSERT INTO rounds(match_id,round_no,game_type,prompt,extra,deadline) VALUES(?,1,?,?,?,?)',(mid,1,g,'حدس عدد ۱ تا ۳۰',json.dumps({'secret':secret}),time.time()+60))
  await announce(ctx,mid,'🔢 عددی بین ۱ تا ۳۰ حدس بزن و آن را برای ربات بفرست. زمان ۶۰ ثانیه است.');TASKS[mid]=asyncio.create_task(number_timeout(ctx,mid));return
 await new_round(ctx,mid,1)
async def new_round(ctx,mid,no):
 with db() as c:
  m=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
  if not m or m['status']!='running':return
  row=c.execute('SELECT * FROM questions WHERE game_type=? AND active=1 ORDER BY RANDOM() LIMIT 1',(m['game_type'],)).fetchone()
  if not row:row=c.execute("SELECT * FROM questions WHERE game_type='quiz' AND active=1 ORDER BY RANDOM() LIMIT 1").fetchone()
  if not row:return await finish(ctx,mid)
  opts=json.loads(row['options']);deadline=time.time()+SECONDS
  rid=c.execute('INSERT INTO rounds(match_id,round_no,game_type,prompt,options,answer,deadline) VALUES(?,?,?,?,?,?,?)',(mid,no,m['game_type'],row['prompt'],json.dumps(opts,ensure_ascii=False),row['answer'],deadline)).lastrowid
 for p in players(mid):await send(ctx,p['user_id'],f'🎯 دور {no}\n{row["prompt"]}\n⏱ {SECONDS} ثانیه',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'{i+1}. {v}',callback_data=f'ans:{rid}:{i}')] for i,v in enumerate(opts)]))
 TASKS[mid]=asyncio.create_task(round_timeout(ctx,mid,rid,no))
async def answer(q,ctx,uid,rid,val):
 with db() as c:
  r=c.execute('SELECT * FROM rounds WHERE id=?',(rid,)).fetchone()
  if not r or r['status']!='open' or time.time()>r['deadline']:return await q.answer('زمان پاسخ تمام شده.',show_alert=True)
  if not c.execute('SELECT 1 FROM players WHERE match_id=? AND user_id=?',(r['match_id'],uid)).fetchone():return await q.answer('عضو مسابقه نیستی.',show_alert=True)
  if c.execute('SELECT 1 FROM answers WHERE round_id=? AND user_id=?',(rid,uid)).fetchone():return await q.answer('پاسخ قبلاً ثبت شده.',show_alert=True)
  ok=int(int(val)==r['answer']);pts=10 if ok else 0;c.execute('INSERT INTO answers(round_id,user_id,answer,correct,points) VALUES(?,?,?,?,?)',(rid,uid,val,ok,pts));c.execute('UPDATE players SET score=score+? WHERE match_id=? AND user_id=?',(pts,r['match_id'],uid))
  done=c.execute('SELECT COUNT(*) n FROM answers WHERE round_id=?',(rid,)).fetchone()['n']>=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(r['match_id'],)).fetchone()['n']
 await q.answer('درست بود! +۱۰ امتیاز' if ok else 'پاسخ ثبت شد.',show_alert=True)
 if done:await close_round(ctx,r['match_id'],rid,r['round_no'])
async def round_timeout(ctx,mid,rid,no):await asyncio.sleep(SECONDS+1);await close_round(ctx,mid,rid,no)
async def close_round(ctx,mid,rid,no):
 with db() as c:
  r=c.execute('SELECT * FROM rounds WHERE id=?',(rid,)).fetchone()
  if not r or r['status']!='open':return
  c.execute("UPDATE rounds SET status='closed' WHERE id=?",(rid,));n=c.execute('SELECT COUNT(*) n FROM answers WHERE round_id=?',(rid,)).fetchone()['n'];total=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(mid,)).fetchone()['n']
 await announce(ctx,mid,f'⌛ دور {no} تمام شد؛ پاسخ‌ها {n}/{total}')
 if no>=5:await finish(ctx,mid)
 else:await new_round(ctx,mid,no+1)
async def number_timeout(ctx,mid):await asyncio.sleep(61);await finish(ctx,mid)
async def game_text(update,ctx):
 m=active(update.effective_user.id)
 if not m or m['status']!='running' or m['game_type']!='number':return False
 try:g=int(update.message.text.strip())
 except ValueError:return True
 with db() as c:
  r=c.execute("SELECT * FROM rounds WHERE match_id=? AND status='open' ORDER BY id DESC LIMIT 1",(m['id'],)).fetchone()
  if not r:return True
  if c.execute('SELECT 1 FROM answers WHERE round_id=? AND user_id=?',(r['id'],update.effective_user.id)).fetchone():await update.message.reply_text('حدس قبلی ثبت شده است.');return True
  secret=json.loads(r['extra'])['secret'];ok=g==secret;pts=15 if ok else 0;c.execute('INSERT INTO answers(round_id,user_id,answer,correct,points) VALUES(?,?,?,?,?)',(r['id'],update.effective_user.id,str(g),int(ok),pts));c.execute('UPDATE players SET score=score+? WHERE match_id=? AND user_id=?',(pts,m['id'],update.effective_user.id))
 await update.message.reply_text('🎉 درست حدس زدی! +۱۵ امتیاز' if ok else '❌ درست نیست؛ دوباره حدس بزن.')
 if ok:await finish(ctx,m['id'])
 return True
async def finish(ctx,mid):
 with db() as c:
  m=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
  if not m or m['status'] in ('finished','cancelled'):return
  ps=c.execute('SELECT p.user_id,p.score,u.full_name FROM players p JOIN users u ON u.user_id=p.user_id WHERE p.match_id=? ORDER BY p.score DESC,p.joined_at',(mid,)).fetchall();best=ps[0]['score'] if ps else 0
  c.execute("UPDATE matches SET status='finished',ended_at=CURRENT_TIMESTAMP WHERE id=?",(mid,))
  for p in ps:
   win=int(p['score']==best and best>0);c.execute('UPDATE users SET total_points=total_points+?,games=games+1,wins=wins+?,losses=losses+?,level=1+CAST((total_points+?)/100 AS INTEGER) WHERE user_id=?',(p['score'],win,int(not win),p['score'],p['user_id']))
 if mid in TASKS:
  task=TASKS.pop(mid,None)
  if task and task is not asyncio.current_task():task.cancel()
 msg='🏁 نتیجه نهایی\n'+'\n'.join(f'{i}. {p["full_name"]} — {p["score"]} امتیاز' for i,p in enumerate(ps,1))
 for p in ps:await send(ctx,p['user_id'],msg,reply_markup=MENU)
async def cancel(q,ctx,uid,mid):
 with db() as c:
  m=c.execute('SELECT * FROM matches WHERE id=?',(mid,)).fetchone()
  if not m or (m['host_id']!=uid and uid!=ADMIN_ID):return await q.message.reply_text('فقط میزبان می‌تواند لغو کند.')
  c.execute("UPDATE matches SET status='cancelled',ended_at=CURRENT_TIMESTAMP WHERE id=?",(mid,))
 await announce(ctx,mid,'❌ مسابقه لغو شد.');await q.message.reply_text('اتاق لغو شد.')
async def leave(q,uid,mid):
 with db() as c:
  c.execute('DELETE FROM players WHERE match_id=? AND user_id=?',(mid,uid));n=c.execute('SELECT COUNT(*) n FROM players WHERE match_id=?',(mid,)).fetchone()['n'];m=c.execute('SELECT host_id FROM matches WHERE id=?',(mid,)).fetchone()
  if n==0:c.execute("UPDATE matches SET status='cancelled' WHERE id=?",(mid,))
  elif m and m['host_id']==uid:
   h=c.execute('SELECT user_id FROM players WHERE match_id=? ORDER BY joined_at LIMIT 1',(mid,)).fetchone();c.execute('UPDATE matches SET host_id=? WHERE id=?',(h['user_id'],mid))
 await q.message.reply_text('از مسابقه خارج شدی.')
async def profile(update,ctx):
 uid=update.effective_user.id
 with db() as c:u=c.execute('SELECT * FROM users WHERE user_id=?',(uid,)).fetchone();rank=c.execute('SELECT COUNT(*)+1 r FROM users WHERE total_points>(SELECT total_points FROM users WHERE user_id=?)',(uid,)).fetchone()['r']
 await update.message.reply_text(f'👤 پروفایل\nنام: {u["full_name"]}\nشناسه: {uid}\nامتیاز: {u["total_points"]}\nمسابقات: {u["games"]}\nبرد: {u["wins"]} | باخت: {u["losses"]}\nسطح: {u["level"]}\nرتبه: {rank}')
async def leaderboard(update,ctx):
 with db() as c:rs=c.execute('SELECT full_name,total_points FROM users WHERE blocked=0 ORDER BY total_points DESC LIMIT 10').fetchall()
 await update.message.reply_text('🏆 ۱۰ نفر برتر\n'+'\n'.join(f'{i}. {r["full_name"]} — {r["total_points"]}' for i,r in enumerate(rs,1)))
async def history(update,ctx):
 with db() as c:rs=c.execute('SELECT m.id,m.game_type,m.status,p.score FROM players p JOIN matches m ON m.id=p.match_id WHERE p.user_id=? ORDER BY m.id DESC LIMIT 10',(update.effective_user.id,)).fetchall()
 await update.message.reply_text('📜 تاریخچه\n'+'\n'.join(f'#{r["id"]} {GAMES.get(r["game_type"],"- ")} | {r["status"]} | {r["score"]} امتیاز' for r in rs) if rs else 'هنوز مسابقه‌ای نداری.')
async def finish_cmd(update,ctx):
 m=active(update.effective_user.id)
 if not m:return await update.message.reply_text('مسابقه فعالی نداری.')
 if m['host_id']!=update.effective_user.id and update.effective_user.id!=ADMIN_ID:return await update.message.reply_text('فقط میزبان می‌تواند پایان دهد.')
 await finish(ctx,m['id'])
async def admin(update,ctx):
 if update.effective_user.id!=ADMIN_ID:return
 with db() as c:
  u=c.execute('SELECT COUNT(*) n FROM users').fetchone()['n'];a=c.execute("SELECT COUNT(*) n FROM users WHERE last_seen>=datetime('now','-1 day')").fetchone()['n'];m=c.execute('SELECT COUNT(*) n FROM matches').fetchone()['n'];r=c.execute("SELECT COUNT(*) n FROM matches WHERE status IN ('waiting','selecting','running')").fetchone()['n'];rep=c.execute("SELECT COUNT(*) n FROM reports WHERE status='new'").fetchone()['n']
 await update.message.reply_text(f'🛠 پنل مدیریت\nکاربران: {u}\nفعال ۲۴ ساعت: {a}\nکل مسابقات: {m}\nمسابقات فعال: {r}\nگزارش‌های جدید: {rep}',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton('مسابقات فعال',callback_data='admin:matches')],[InlineKeyboardButton('گزارش‌ها',callback_data='admin:reports')],[InlineKeyboardButton('افزودن سؤال',callback_data='admin:addq')],[InlineKeyboardButton('پیام همگانی',callback_data='admin:broadcast')]]))
async def admin_callback(q,ctx,uid,d):
 if uid!=ADMIN_ID:return await q.answer('دسترسی ندارید.',show_alert=True)
 a=d.split(':')[1]
 if a=='matches':
  with db() as c:rs=c.execute("SELECT id,kind,status,host_id FROM matches WHERE status IN ('waiting','selecting','running') ORDER BY id DESC LIMIT 20").fetchall()
  await q.message.reply_text('\n'.join(f'#{r["id"]} {r["kind"]} {r["status"]} میزبان:{r["host_id"]}' for r in rs) or 'مسابقه فعالی نیست.',reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton(f'پایان #{r["id"]}',callback_data=f'admfinish:{r["id"]}'),InlineKeyboardButton(f'لغو #{r["id"]}',callback_data=f'admcancel:{r["id"]}')] for r in rs]))
 elif a=='reports':
  with db() as c:rs=c.execute("SELECT id,user_id,match_id,reason FROM reports WHERE status='new' ORDER BY id DESC LIMIT 20").fetchall()
  await q.message.reply_text('\n'.join(f'#{r["id"]} کاربر:{r["user_id"]} مسابقه:{r["match_id"]} {r["reason"]}' for r in rs) or 'گزارش جدیدی نیست.')
 elif a in ('addq','broadcast'):ctx.user_data['admin']=a;await q.message.reply_text('پیام همگانی را بفرست.' if a=='broadcast' else 'قالب: نوع|دسته|سطح|متن سؤال|گزینه۱;گزینه۲;گزینه۳;گزینه۴|شماره پاسخ درست')
async def admin_text(update,ctx):
 a=ctx.user_data.pop('admin');t=update.message.text
 if a=='broadcast':
  with db() as c:ids=[x['user_id'] for x in c.execute('SELECT user_id FROM users WHERE blocked=0')]
  ok=0
  for uid in ids:
   if await send(ctx,uid,'📣 پیام مدیریت:\n'+t):ok+=1
  await update.message.reply_text(f'ارسال شد: {ok}/{len(ids)}')
 else:
  try:
   g,cat,diff,p,opts,ans=[x.strip() for x in t.split('|',5)];o=[x.strip() for x in opts.split(';')];ans=int(ans)-1
   if g not in ('quiz','word','riddle','speed') or len(o)<2 or ans not in range(len(o)):raise ValueError()
   with db() as c:c.execute('INSERT INTO questions(game_type,category,difficulty,prompt,options,answer) VALUES(?,?,?,?,?,?)',(g,cat,diff,p,json.dumps(o,ensure_ascii=False),ans))
   await update.message.reply_text('✅ سؤال اضافه شد.')
  except Exception:await update.message.reply_text('قالب سؤال نامعتبر است.')
 return True
async def block(update,ctx):
 if update.effective_user.id!=ADMIN_ID:return
 try:uid=int(ctx.args[0])
 except:return await update.message.reply_text('استفاده: /block شناسه')
 with db() as c:c.execute('UPDATE users SET blocked=1 WHERE user_id=?',(uid,))
 await update.message.reply_text('کاربر مسدود شد.')
async def unblock(update,ctx):
 if update.effective_user.id!=ADMIN_ID:return
 try:uid=int(ctx.args[0])
 except:return await update.message.reply_text('استفاده: /unblock شناسه')
 with db() as c:c.execute('UPDATE users SET blocked=0 WHERE user_id=?',(uid,))
 await update.message.reply_text('مسدودی رفع شد.')
async def report_cmd(update,ctx):
 m=active(update.effective_user.id)
 if not m:return await update.message.reply_text('مسابقه فعالی نداری.')
 with db() as c:c.execute('INSERT INTO reports(user_id,match_id,reason) VALUES(?,?,?)',(update.effective_user.id,m['id'],'گزارش کاربر'))
 await update.message.reply_text('گزارش ثبت شد.')
async def post_init(app):
 init_db()
 with db() as c:rs=c.execute("SELECT id,status FROM matches WHERE status IN ('waiting','selecting','running')").fetchall();c.execute("UPDATE rounds SET status='closed' WHERE status='open' AND deadline<?",(time.time(),))
 for r in rs:
  for p in players(r['id']):await send(app,p['user_id'],'🔄 ربات راه‌اندازی مجدد شد؛ وضعیت مسابقه حفظ شده است. میزبان می‌تواند با /finish آن را پایان دهد.')
 me=await app.bot.get_me();log.info('Started @%s database=%s',me.username,DB_PATH)
async def on_error(update,ctx):event('error',str(ctx.error))
async def main():
 if not TOKEN:raise RuntimeError('BOT_TOKEN تنظیم نشده است.')
 init_db();app=Application.builder().token(TOKEN).post_init(post_init).build()
 for cmd,fn in [('start',start),('help',help_cmd),('admin',admin),('finish',finish_cmd),('report',report_cmd),('block',block),('unblock',unblock)]:app.add_handler(CommandHandler(cmd,fn))
 app.add_handler(CallbackQueryHandler(callbacks));app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND,text_router));app.add_error_handler(on_error)
 await app.initialize();await post_init(app);await app.start();await app.updater.start_polling(drop_pending_updates=False)
 try:
  while True:await asyncio.sleep(3600)
 finally:await app.updater.stop();await app.stop();await app.shutdown()
if __name__=='__main__':
 try:asyncio.run(main())
 except KeyboardInterrupt:pass
