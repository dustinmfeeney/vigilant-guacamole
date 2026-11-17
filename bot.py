import os
import io
import sys
import time
import json
import sqlite3
import asyncio
import secrets
from urllib.parse import urlencode
import aiohttp
from aiohttp import web
import discord
from discord import app_commands
from discord.ext import commands
from dotenv import load_dotenv
from google import genai
from google.genai import types

load_dotenv()

DISCORD_TOKEN = os.getenv("DISCORD_TOKEN", "").strip()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
DISCORD_GUILD_ID = os.getenv("DISCORD_GUILD_ID", "").strip()
MSF_API_KEY = os.getenv("MSF_API_KEY", "").strip()
MSF_CLIENT_ID = os.getenv("MSF_CLIENT_ID", "").strip()
MSF_CLIENT_SECRET = os.getenv("MSF_CLIENT_SECRET", "").strip()
OAUTH_REDIRECT_URI = os.getenv("OAUTH_REDIRECT_URI", "http://localhost:8080/callback").strip()
PORT = int(os.getenv("PORT", "8080"))

if not DISCORD_TOKEN or not GEMINI_API_KEY:
    print("ERROR: Missing DISCORD_TOKEN or GEMINI_API_KEY in environment variables.")
    sys.exit(1)

ai_client = genai.Client(api_key=GEMINI_API_KEY)
ACTIVE_MODEL = "gemini-3.8-flash"
def generate_with_retry(contents, config):
    for attempt in range(4):
        try:
            return ai_client.models.generate_content(
                model=ACTIVE_MODEL,
                contents=contents,
                config=config
            )
        except Exception as e:
            if ("503" in str(e) or "UNAVAILABLE" in str(e)) and attempt < 3:
                time.sleep(2 * (attempt + 1))
                continue
            raise

async def call_gemini_resilient(contents):
    last_err = None
    for model_name in MODEL_CHAIN:
        for attempt in range(2):
            try:
                return await asyncio.wait_for(
                    asyncio.to_thread(
                        ai_client.models.generate_content,
                        model=model_name,
                        contents=contents,
                        config=types.GenerateContentConfig(system_instruction=MASTER_ENGINE_PROMPT, temperature=0.2)
                    ),
                    timeout=30.0
                )
            except Exception as exc:
                last_err = exc
                if "503" in str(exc) or "UNAVAILABLE" in str(exc) or "429" in str(exc):
                    await asyncio.sleep(1.5)
                    continue
                break
    raise last_err




pending_oauth_states: dict[str, tuple[str, float]] = {}

MASTER_ENGINE_PROMPT = """
You are the Master Marvel Strike Force (MSF) Tactical Battle Dismantler & Roster Strategist.
Do 99% of the heavy lifting automatically:
- When a screenshot is attached, auto-detect Game Mode, Room/Stage, Exhaust stacks, and all 5 Enemy Characters (Gear Tier, Filled Stars/Diamonds, TCP) left-to-right.
- Cross-reference the player's auto-synced MSF.gg roster, Saved Squads, Inventory, Stark Tech, and Auto-Detected Recent Upgrades.

### CORE COMBAT MATH & LIVE NOVEMBER 2026 RULES:
1. **True Stat Weighting & Auto-Locks:**
   - Prioritize **Gear Tier (G17-G21), Character Level (90-110), Complete Ability Levels (Basic/Special/Ult/Passive + Awakened), and Iso-8 Tier/Class (Green -> Purple -> Orange Tier 3)** over raw TCP.
   - Flag Low-Level / High-Diamond opponents as **Paper Tigers / Fake Traps**.
   - Enforce **Exhausted** math: -20% Armor, Damage, Focus, and Resistance + 20% incoming damage per stack (up to 4 stacks / -80%); Speed & Accuracy unchanged.
   - Exclude all **Defense-Locked** and **Already-Spent Offense** characters in War and Cosmic Crucible.

2. **Active Season & Mode-Specific Rules:**
   - **Arena:** Strip all War/Crucible/Raid/Battleworld mode-locked clauses. Pure Speed, Battlefield Effect overwrites, and kit collisions. No reuse lock.
   - **Alliance War (Savage Showdown):** Blue Marvel (Ult) & Xavier (Special) gain 2 Exhausted; Menace allies gain Revive Once; Enemy Xavier cannot Mind Control; Exhausted enemies cannot reduce negative effect durations; Armory flips ALL effects on attacking allies with Defense Down on turn; Savage Land (3+ allies: Sauron freezes enemy Speed Bar fill/reduction & applies 2-turn Ability Block to Brawlers on Ult; Cyclops Mighty blocks enemy Speed Up until his turn & grants Slow immunity; Ka-Zar gains Defense Up/Immunity after all other On-Spawn effects); West Coast Avengers flip Offense Down on turn; War Tech Tiers 1-7 (Tier 7 Opening Gambit: 90% permanent Max HP damage to fastest unit on spawn—ignores Deathproof/Barrier); Helicarrier adjacent buffs; Reinforcements.
   - **Cosmic Crucible (Season 25):** Stage 2 Skirmishers flip all negative effects on self on successful hit (unless Trauma); Stage 3 bonus Iso-8 attack after primary active turn attack if target has Bleed (fires once per action); Dread crits apply +1 Contagion & +5% Crit Chance/Damage; AI Avengers Repair grants immunity to Blind, Trauma, Silence, Defense Down, Stun; Hybrid Raid/War tags; maximum Victory Point (VP) survival/turn efficiency.
   - **Trepidation Raids & Boss Raid:** Pre-loaded enemy Speed Bar (50%-100%), carryover cooldowns/HP, wave drops, required teams (Insidious 6, Immortal Weapons, Champions, Amazing Avengers, Hellfire Club, Iron Raiders).
   - **Battleworld (Fallen Asgard):** Difficulties 1-5 (D4: Lv105/G20; D5: Lv110/2D/G21/Purple Iso-5), Destroyer auto-complete, Dual-Trait locks, Power/Armor/Speed Tokens (0-10: +4% Dmg, +4% Armor, +2 flat Speed per token).
   - **Dark Dimension (DD1-DD9 & Sagas):** Hard entry gates (DD6 G18, DD7 G19, DD8 Purple Iso-3 + Hero/Villain splits, Xavier Saga G20, Blue Marvel Trials Purple Iso-4/5 Conqueror, DD9 G21) + node-to-node carryover.

3. **4-Button Speed, Status, Iso-8 & Hit-Resolution Math:**
   - Audit **Basic, Special, Ultimate, and Passive** for Speed Bar fills/rewinds, permanent speed drops (Emma Frost -10%), buff-driven speed engines (Old Man Logan, Super-Skrull Hero/Villain count +10% Speed Bar per buff/debuff), Speed-Bar blockers (Captain Britain, Xavier, Spider-Man Big Time, Sauron), and 1,000-point overflow tiebreakers.
   - **3-Gate Debuff Order:** (1) Safeguard Strip/Duration-Reduce -> (2) Immunity / Personalized Immunity (blocks even "Cannot be resisted" unless "Ignores Immunity") -> (3) Individual Acting Unit Focus vs. Resistance.
   - Track **Trauma, Silence, Safeguard, Vulnerable, Exposed (neutral; bypasses Immunity & cleanses), Personalized Buffs (Breaker, Galactic Council Cosmic Control Rod blocking Charged, Gilgamesh Eternal Saga, Maestro Wrath/Galvanize, Blastaar Bomb Burst), and Battlefield Effects (Odin, Mephisto, Xavier, Franklin Richards, Quasar)**.
   - **All 5 Iso-8 Classes:** Striker (primary active turn only vs. double-trigger traps), Skirmisher (+50% Focus + Vulnerable buff strips), Raider (AoE crit Vulnerable), Healer (7-Yellow-Star baseline Minor Regen 5% / Regen 10% / Active Heal + Special/Ult Vulnerable cleanse + Orange Iso-3 Vulnerable flip), Fortifier (30% Max HP Barrier cap + self-Vulnerable cleanse + Orange Iso-3 Taunt team cleanse).
   - Multiplicative **Permanent Max Health Reductions** vs. **Percentage Health Steals** (bypass Heal Block & Deflect).
   - Separate **Natural Dodge, Evade (not consumed by Unavoidable), Cannot Be Dodged (misses if Blinded), Unavoidable (ignores Blind/Dodge/Evade; can still be Blocked), Cannot Be Blocked, Non-Attack Blind bypass, Blind Immunity/High Accuracy, Counterattack vs. Passive On-Hit, Deathproof multi-hit math, Charge caps (1-20+), No-Revive Kills, and Summon On-Death triggers**.

4. **Dynamic 5-Man M/W Positioning & 3-Run RNG Stress Test:**
   - Map **M/W Grid** (`Slots 1, 3, 5 Front` | `Slots 2, 4 Back Pockets`) dynamically for full teams vs. hybrids, isolating Adjacent Splash, tucking Energy Batteries in Back Pockets, breaking Chains, dodging Row Attacks, and preventing Taunt + Stealth conflicts.
   - Run **3 RNG Stress Tests** (Run 1 Baseline, Run 2 Adverse Resist/Dodge/Crit, Run 3 Worst-Case Tiebreaker/Random-Target AI).

### REQUIRED OUTPUT FORMAT:
Line 1 MUST be plain text: `RECOMMENDED_5: Toon1, Toon2, Toon3, Toon4, Toon5`
Then output cleanly and concisely (under 4,500 characters total):
1. **VERDICT:** `[Easy Win (1-Shot) / Risky Win (1-Shot) / Coin Flip Toss / Planned 2-Tap / Wipe]` + 1-sentence reason.
2. **BEST TEAM & M/W POSITIONING (Slots 1–5):**
   - `Slot 1 (Front-Left):` Name — How they help your team + Iso-8 fit
   - `Slot 2 (Back-Left):` Name — Role + Iso-8 fit
   - `Slot 3 (Front-Center):` Name — Role + Iso-8 fit
   - `Slot 4 (Back-Right):` Name — Role + Iso-8 fit
   - `Slot 5 (Front-Right):` Name — Role + Iso-8 fit
3. **KILL ORDER & TURN-BY-TURN MOVES:**
   - **Kill Order:** 1st -> Last
   - **Moves:** Turn-by-turn script + **RNG Alternate Pivot** + **"DO NOT PRESS"** warning.
4. **ALT OPTIONS (Budget / Zero-Iso-Swap / 2-Tap):**
   - Filtered strictly to what the player actually has built.
"""

db_lock = asyncio.Lock()

def get_db():
    conn = sqlite3.connect("msf_bot.db", timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    return conn

def init_db():
    conn = get_db()
    conn.execute("""
        CREATE TABLE IF NOT EXISTS users (
            discord_id TEXT PRIMARY KEY,
            access_token TEXT,
            refresh_token TEXT,
            roster_json TEXT,
            squads_json TEXT,
            inventory_json TEXT,
            stark_tech_json TEXT,
            last_sync TEXT,
            defense_locks TEXT DEFAULT '[]',
            spent_offense TEXT DEFAULT '[]',
            extra_notes TEXT DEFAULT 'None'
        )
    """)
    existing_cols = {row["name"] for row in conn.execute("PRAGMA table_info(users);").fetchall()}
    required_cols = {
        "squads_json": "TEXT",
        "inventory_json": "TEXT",
        "stark_tech_json": "TEXT",
        "last_sync": "TEXT",
        "defense_locks": "TEXT DEFAULT '[]'",
        "spent_offense": "TEXT DEFAULT '[]'",
        "extra_notes": "TEXT DEFAULT 'None'"
    }
    for col, col_type in required_cols.items():
        if col not in existing_cols:
            conn.execute(f"ALTER TABLE users ADD COLUMN {col} {col_type};")
    conn.commit()
    conn.close()

def _sync_read_user(discord_id: str) -> dict:
    conn = get_db()
    row = conn.execute("SELECT * FROM users WHERE discord_id = ?", (str(discord_id),)).fetchone()
    conn.close()
    if not row:
        return {}
    data = dict(row)
    data["defense_locks"] = json.loads(data.get("defense_locks") or "[]")
    data["spent_offense"] = json.loads(data.get("spent_offense") or "[]")
    return data

def _sync_write_field(discord_id: str, field: str, value: str):
    conn = get_db()
    conn.execute("INSERT OR IGNORE INTO users (discord_id) VALUES (?)", (str(discord_id),))
    conn.execute(f"UPDATE users SET {field} = ? WHERE discord_id = ?", (value, str(discord_id)))
    conn.commit()
    conn.close()

async def db_read_user(discord_id: str) -> dict:
    async with db_lock:
        return await asyncio.to_thread(_sync_read_user, discord_id)

async def db_write_field(discord_id: str, field: str, value: str):
    allowed_fields = {
        "access_token", "refresh_token", "roster_json", "squads_json",
        "inventory_json", "stark_tech_json", "last_sync", "defense_locks",
        "spent_offense", "extra_notes"
    }
    if field not in allowed_fields:
        raise ValueError(f"Invalid database field: {field}")
    async with db_lock:
        await asyncio.to_thread(_sync_write_field, discord_id, field, value)

def compress_roster_for_ai(r_data: dict) -> str:
    lines = []
    for c in r_data.get("data", []):
        if not isinstance(c, dict):
            continue
        cid = c.get("id", "Unknown")
        lv = c.get("level", 1)
        gt = c.get("tier", 1)
        power = c.get("power", 0)
        stars = f"{c.get('stars', 0)}Y/{c.get('redStars', 0)}R/{c.get('diamonds', 0)}D"
        abil = f"{c.get('basic', 1)}/{c.get('special', 1)}/{c.get('ultimate', 1)}/{c.get('passive', 1)}"
        iso = c.get("iso", {})
        iso_str = f"{iso.get('matrix', 'None')}-{iso.get('class', 'None')}" if isinstance(iso, dict) else str(iso)
        lines.append(f"{cid} | TCP:{power} | Lv{lv} | G{gt} | {stars} | {abil} | Iso:{iso_str}")
    return "\n".join(lines) if lines else json.dumps(r_data)[:25000]

def detect_roster_changes(old_raw: str, new_data: dict) -> str:
    if not old_raw:
        return "Initial MSF.gg roster sync completed."
    try:
        old_data = json.loads(old_raw)
        old_chars = {c.get("id"): c for c in old_data.get("data", []) if isinstance(c, dict)}
        new_chars = {c.get("id"): c for c in new_data.get("data", []) if isinstance(c, dict)}
        changes = []
        for cid, nc in new_chars.items():
            oc = old_chars.get(cid)
            if not oc:
                changes.append(f"Unlocked **{cid}** (Lv {nc.get('level')}, G{nc.get('tier')})")
                continue
            diffs = []
            if nc.get("level") != oc.get("level"):
                diffs.append(f"Lv {oc.get('level')}->{nc.get('level')}")
            if nc.get("tier") != oc.get("tier"):
                diffs.append(f"G{oc.get('tier')}->G{nc.get('tier')}")
            if (nc.get("stars"), nc.get("redStars"), nc.get("diamonds")) != (oc.get("stars"), oc.get("redStars"), oc.get("diamonds")):
                diffs.append("Stars/Diamonds upgraded")
            if (nc.get("basic"), nc.get("special"), nc.get("ultimate"), nc.get("passive")) != (oc.get("basic"), oc.get("special"), oc.get("ultimate"), oc.get("passive")):
                diffs.append("Ability/T4 upgraded")
            if nc.get("iso") != oc.get("iso"):
                diffs.append("Iso-8 updated")
            if diffs:
                changes.append(f"**{cid}** ({', '.join(diffs)})")
        return "; ".join(changes[:10]) if changes else "No new upgrades since last check."
    except Exception:
        return "Roster refreshed."

def extract_defense_from_squads(squads_data: dict) -> list[str]:
    locked = set()
    try:
        for sq in squads_data.get("data", []):
            name = str(sq.get("name", "")).lower()
            if "def" in name or "defense" in name:
                for member in sq.get("characters", []):
                    if isinstance(member, str):
                        locked.add(member)
                    elif isinstance(member, dict) and member.get("id"):
                        locked.add(member["id"])
    except Exception:
        pass
    return list(locked)
async def sync_and_get_context(discord_id: str) -> tuple[str, str]:
    user = await db_read_user(discord_id)
    if not user or not user.get("access_token"):
        if user.get("roster_json"):
            return f"SYNCED_CSV (Last updated: {user.get('last_sync', 'Recent')}):\n{user['roster_json'][:28000]}", "Using uploaded CSV roster."
        return "UNLINKED_ROSTER: Player has not linked MSF.gg yet.", "Tip: Run `/connect` once so I remember your roster automatically!"

    headers = {"Authorization": f"Bearer {user['access_token']}", "x-api-key": MSF_API_KEY}
    timeout = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async def fetch_all(auth_headers):
            r_resp = await session.get("https://marvelstrikeforce.com", headers=auth_headers)
            if r_resp.status != 200:
                return r_resp.status, None, None, None, None
            r_json = await r_resp.json()
            s_resp = await session.get("https://marvelstrikeforce.com", headers=auth_headers)
            s_json = await s_resp.json() if s_resp.status == 200 else {}
            i_resp = await session.get("https://marvelstrikeforce.com", headers=auth_headers)
            i_json = await i_resp.json() if i_resp.status == 200 else {}
            c_resp = await session.get("https://marvelstrikeforce.com", headers=auth_headers)
            c_json = await c_resp.json() if c_resp.status == 200 else {}
            return 200, r_json, s_json, i_json, c_json

        status, r_data, s_data, i_data, c_data = await fetch_all(headers)

        if status == 401 and user.get("refresh_token"):
            payload = {
                "grant_type": "refresh_token",
                "refresh_token": user["refresh_token"],
                "client_id": MSF_CLIENT_ID,
                "client_secret": MSF_CLIENT_SECRET
            }
            async with session.post("https://marvelstrikeforce.com", data=payload) as t_resp:
                if t_resp.status == 200:
                    tokens = await t_resp.json()
                    await db_write_field(discord_id, "access_token", tokens["access_token"])
                    if "refresh_token" in tokens:
                        await db_write_field(discord_id, "refresh_token", tokens["refresh_token"])
                    headers["Authorization"] = f"Bearer {tokens['access_token']}"
                    status, r_data, s_data, i_data, c_data = await fetch_all(headers)

        if status == 200 and r_data:
            change_summary = detect_roster_changes(user.get("roster_json"), r_data)
            await db_write_field(discord_id, "roster_json", json.dumps(r_data))
            await db_write_field(discord_id, "squads_json", json.dumps(s_data))
            await db_write_field(discord_id, "inventory_json", json.dumps(i_data))
            await db_write_field(discord_id, "stark_tech_json", json.dumps(c_data))
            await db_write_field(discord_id, "last_sync", str(discord.utils.utcnow()))

            auto_def = extract_defense_from_squads(s_data)
            if auto_def:
                await db_write_field(discord_id, "defense_locks", json.dumps(auto_def))

            compact_roster = compress_roster_for_ai(r_data)
            combined = (
                f"LIVE_ROSTER (FULL):\n{compact_roster}\n\n"
                f"SAVED_SQUADS:\n{json.dumps(s_data)[:3000]}\n\n"
                f"INVENTORY & STARK TECH:\n{json.dumps(i_data)[:2000]} | {json.dumps(c_data)[:1500]}"
            )
            return combined, change_summary

    return f"CACHED_ROSTER:\n{user.get('roster_json', '')[:28000]}", "Using cached roster snapshot."

class BattleActionView(discord.ui.View):
    def __init__(self, user_id: str, recommended_toons: list[str]):
        super().__init__(timeout=3600)
        self.user_id = str(user_id)
        self.recommended_toons = recommended_toons

    @discord.ui.button(label="Mark Team Used (Lock for Round)", style=discord.ButtonStyle.green, emoji="✅")
    async def mark_used(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Only the player who ran this battle can lock their own team.", ephemeral=True)
            return
        user = await db_read_user(self.user_id)
        spent = set(user.get("spent_offense", []))
        spent.update(self.recommended_toons)
        await db_write_field(self.user_id, "spent_offense", json.dumps(list(spent)))
        button.disabled = True
        button.label = "Team Locked for Round"
        await interaction.response.edit_message(view=self)
        await interaction.followup.send(f"Locked **{', '.join(self.recommended_toons)}** for the rest of this round!", ephemeral=True)

    @discord.ui.button(label="Reset Round Locks", style=discord.ButtonStyle.secondary, emoji="🔄")
    async def reset_round(self, interaction: discord.Interaction, button: discord.ui.Button):
        if str(interaction.user.id) != self.user_id:
            await interaction.response.send_message("Only the player who ran this battle can reset their own locks.", ephemeral=True)
            return
        await db_write_field(self.user_id, "spent_offense", "[]")
        await interaction.response.send_message("Cleared all spent Offense locks for your new War/Crucible round!", ephemeral=True)

class SmartMSFBot(commands.Bot):
    def __init__(self):
        super().__init__(command_prefix="!", intents=discord.Intents.default())
        self.web_runner = None

    async def handle_oauth_callback(self, request: web.Request):
        now = time.time()
        expired_keys = [k for k, (_, exp) in pending_oauth_states.items() if exp < now]
        for k in expired_keys:
            pending_oauth_states.pop(k, None)

        code = request.query.get("code")
        state = request.query.get("state")
        entry = pending_oauth_states.pop(state, None)
        if not code or not entry:
            return web.Response(text="Invalid or expired login link. Please run /connect in Discord again.", status=400)

        discord_id, _ = entry
        payload = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": OAUTH_REDIRECT_URI,
            "client_id": MSF_CLIENT_ID,
            "client_secret": MSF_CLIENT_SECRET
        }
        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post("https://marvelstrikeforce.com", data=payload) as resp:
                if resp.status == 200:
                    tokens = await resp.json()
                    await db_write_field(discord_id, "access_token", tokens["access_token"])
                    if "refresh_token" in tokens:
                        await db_write_field(discord_id, "refresh_token", tokens["refresh_token"])
                    await sync_and_get_context(discord_id)
                    try:
                        user_obj = await self.fetch_user(int(discord_id))
                        await user_obj.send("✅ **MSF.gg Connected & Synced!** Your roster, saved squads, and Stark Tech are now active for `/fight` and `/build`.")
                    except Exception:
                        pass
                    return web.Response(text="MSF.gg Connected! You can close this tab and return to Discord.")
        return web.Response(text="Failed to complete MSF.gg authorization. Try /connect again.", status=500)

    async def setup_hook(self):
        init_db()
        app = web.Application()
        app.router.add_get("/callback", self.handle_oauth_callback)
        self.web_runner = web.AppRunner(app)
        await self.web_runner.setup()
        try:
            site = web.TCPSite(self.web_runner, "0.0.0.0", PORT)
            await site.start()
        except OSError as err:
            print(f"Warning: OAuth2 web listener skipped (port {PORT} unavailable: {err}). CSV & Screenshot modes remain active.")

        if DISCORD_GUILD_ID:
            guild = discord.Object(id=int(DISCORD_GUILD_ID))
            self.tree.copy_global_to(guild=guild)
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"MSF Tactical Bot online as {self.user} (ID: {self.user.id})")

    async def close(self):
        if self.web_runner:
            await self.web_runner.cleanup()
        await super().close()

bot = SmartMSFBot()

def format_discord_output(
    title: str,
    raw_text: str,
    change_banner: str,
    color: discord.Color
) -> tuple[list[discord.Embed], list[str], discord.File | None]:
    rec_toons = []
    clean_lines = []
    for line in raw_text.splitlines():
        stripped = line.lstrip("*# ").strip()
        if stripped.startswith("RECOMMENDED_5:"):
            split_line = stripped.split(":", 1)
            if len(split_line) > 1:
                rec_toons = [n.strip("* ") for n in split_line[1].split(",") if n.strip("* ")]
        else:
            clean_lines.append(line)

    body = "\n".join(clean_lines).strip() or "No simulation details returned."
    clean_text = f"*{change_banner}*\n\n{body}"
    extra_file = None

    if len(clean_text) > 5400:
        extra_file = discord.File(io.BytesIO(clean_text.encode("utf-8")), filename="full_battle_plan.txt")
        display_text = clean_text[:5300] + "\n\n*(Full turn-by-turn breakdown attached above as `full_battle_plan.txt`)*"
    else:
        display_text = clean_text

    chunks = [display_text[i:i + 1900] for i in range(0, len(display_text), 1900)]
    embeds = [
        discord.Embed(title=title if i == 0 else f"{title} (Cont.)", description=c, color=color)
        for i, c in enumerate(chunks[:3])
    ]
    return embeds, rec_toons, extra_file

@bot.tree.command(name="connect", description="One-time setup: Link MSF.gg (auto-syncs upgrades & defense), upload CSV, or drop Defense photo")
@app_commands.describe(
    csv_file="Optional: Upload exported MSF.gg CSV",
    defense_screenshot="Optional: Screenshot of your War/Crucible Defense to auto-lock defenders",
    mode_settings="Optional: War Tech tier or Battleworld tokens (e.g., 'War Off T5, BW P8 A6 S10')"
)
async def connect(
    interaction: discord.Interaction,
    csv_file: discord.Attachment = None,
    defense_screenshot: discord.Attachment = None,
    mode_settings: str = None
):
    await interaction.response.defer(ephemeral=True)
    try:
        uid = str(interaction.user.id)
        updates = []

        if csv_file:
            if csv_file.size > 8_000_000:
                await interaction.followup.send("CSV file is too large (must be under 8 MB).", ephemeral=True)
                return
            raw_bytes = await csv_file.read()
            if raw_bytes:
                data = raw_bytes.decode("utf-8", errors="ignore")
                await db_write_field(uid, "roster_json", data[:30000])
                await db_write_field(uid, "last_sync", str(discord.utils.utcnow()))
                updates.append("**MSF.gg CSV Roster** saved!")

        if defense_screenshot:
            if defense_screenshot.size > 8_000_000:
                await interaction.followup.send("Defense screenshot is too large (must be under 8 MB).", ephemeral=True)
                return
            img_bytes = await defense_screenshot.read()
            if img_bytes:
                vis = await ai_client.aio.models.generate_content(
            model=ACTIVE_MODEL,
                    contents=[
                        "List ONLY the exact Marvel Strike Force character names visible in this Defense screenshot as a comma-separated list.",
                        types.Part.from_bytes(data=img_bytes, mime_type=defense_screenshot.content_type or "image/png")
                    ]
                )
                def_list = [x.strip() for x in (vis.text or "").split(",") if x.strip()]
                await db_write_field(uid, "defense_locks", json.dumps(def_list))
                updates.append(f"**Auto-Locked {len(def_list)} Defenders** from your screenshot.")

        if mode_settings:
            await db_write_field(uid, "extra_notes", mode_settings)
            updates.append(f"**Saved Mode Settings:** {mode_settings}")

        if MSF_CLIENT_ID and MSF_CLIENT_SECRET:
            state_token = secrets.token_urlsafe(16)
            pending_oauth_states[state_token] = (uid, time.time() + 900)
            query_params = urlencode({
                "client_id": MSF_CLIENT_ID,
                "response_type": "code",
                "redirect_uri": OAUTH_REDIRECT_URI,
                "state": state_token,
                "scope": "m3p.f.pr.ros m3p.f.pr.inv m3p.f.pr.pro m3p.f.ar.pro offline"
            })
            oauth_url = f"https://marvelstrikeforce.com?{query_params}"
            oauth_line = f"\n\n**[One-Click Auto-Sync With MSF.gg]({oauth_url})**"
        else:
            oauth_line = "\n\n*(Tip: Add `MSF_CLIENT_ID` and `MSF_CLIENT_SECRET` in environment variables for live OAuth2, or attach your CSV/Defense screenshot directly to `/connect`.)*"

        msg = "\n".join(updates) if updates else "Connect your account once—I will remember your profile and auto-detect every future upgrade!"
        embed = discord.Embed(
            title="MSF Smart Account Link",
            description=f"{msg}{oauth_line}",
            color=discord.Color.blue()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)
    except Exception as exc:
        await interaction.followup.send(f"Could not complete `/connect` right now ({exc}). Please try again.", ephemeral=True)

@bot.tree.command(name="status", description="Check your synced MSF.gg status, auto-locked defenders, spent offense & mode tokens")
async def status(interaction: discord.Interaction):
    uid = str(interaction.user.id)
    user = await db_read_user(uid)
    if not user:
        await interaction.response.send_message("No profile saved yet—run `/connect` once to link your MSF.gg roster!", ephemeral=True)
        return
    sync_state = "Live OAuth2 Connected" if user.get("access_token") else ("CSV Uploaded" if user.get("roster_json") else "Not Synced")
    def_str = (", ".join(user.get("defense_locks", [])) or "None")[:1000]
    spent_str = (", ".join(user.get("spent_offense", [])) or "None")[:1000]
    notes_str = (user.get("extra_notes") or "None")[:1000]

    embed = discord.Embed(title="Your Saved MSF Bot Profile", color=discord.Color.teal())
    embed.add_field(name="Sync Status", value=f"{sync_state} (Last: {user.get('last_sync') or 'Never'})", inline=False)
    embed.add_field(name="Defense-Locked Toons", value=def_str, inline=False)
    embed.add_field(name="Spent Offense This Round", value=spent_str, inline=False)
    embed.add_field(name="Saved War Tech / BW Tokens", value=notes_str, inline=False)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@bot.tree.command(name="fight", description="Drop 1 screenshot (or quick note)—bot auto-syncs your upgrades & gives the winning plan")
@app_commands.describe(
    screenshot="Screenshot of the enemy room/node (bot reads mode, room, Exhaust & all 5 enemies automatically)",
    quick_info="Optional note if not using a screenshot (e.g., 'Crucible Room 3: Mephisto, Odin, BK')"
)
async def fight(
    interaction: discord.Interaction,
    screenshot: discord.Attachment = None,
    quick_info: str = "Auto-detect everything from the attached screenshot."
):
    if not screenshot and quick_info == "Auto-detect everything from the attached screenshot.":
        await interaction.response.send_message("Attach a **screenshot** of the enemy room or enter a quick note in `quick_info`!", ephemeral=True)
        return

    if screenshot and screenshot.size > 8_000_000:
        await interaction.response.send_message("Screenshot is too large (must be under 8 MB).", ephemeral=True)
        return

    await interaction.response.defer()
    extra_file = None
    try:
        uid = str(interaction.user.id)
        roster_text, change_banner = await sync_and_get_context(uid)
        user_data = await db_read_user(uid)

        prompt = f"""
### QUICK BATTLE REQUEST
- **User Input / Quick Info:** {quick_info}
- **Auto-Detected Roster Changes Since Last Fight:** {change_banner}
- **Auto-Locked Defenders (Exclude from Offense):** {user_data.get('defense_locks', [])}
- **Already Spent Offense Toons This Round (Exclude):** {user_data.get('spent_offense', [])}
- **Saved War Tech / Battleworld Tokens:** {user_data.get('extra_notes', 'None')}

### PLAYER SYNCED ROSTER DATA:
{roster_text}
"""
        contents = [prompt]
        if screenshot:
            img_bytes = await screenshot.read()
            if img_bytes:
                contents.append(types.Part.from_bytes(data=img_bytes, mime_type=screenshot.content_type or "image/png"))

            print(f"Running /fight with {ACTIVE_MODEL}...")
            response = await asyncio.wait_for(
            asyncio.to_thread(
                generate_with_retry,
                contents,
                types.GenerateContentConfig(system_instruction=MASTER_ENGINE_PROMPT, temperature=0.2)
            ),
            timeout=45.0
        )



        embeds, rec_toons, extra_file = format_discord_output(
            "MSF Tactical Battle Card",
            response.text or "No simulation output generated.",
            change_banner,
            discord.Color.dark_gold()
        )
        send_kwargs = {"embeds": embeds}
        if extra_file:
            send_kwargs["files"] = [extra_file]
        if rec_toons:
            send_kwargs["view"] = BattleActionView(uid, rec_toons)

        await interaction.followup.send(**send_kwargs)
    except Exception as exc:
        await interaction.followup.send(f"Battle simulation hit a temporary error ({exc}). Please try again in a few seconds.")
    finally:
        if extra_file:
            extra_file.close()

@bot.tree.command(name="build", description="Should you build this toon or leave them alone? (+ exact Gold/Mats/T4s from your roster)")
@app_commands.describe(character="Character name (e.g., Sauron, Sabretooth Breaker, Oath)")
async def build(interaction: discord.Interaction, character: str):
    await interaction.response.defer()
    extra_file = None
    try:
        uid = str(interaction.user.id)
        roster_text, change_banner = await sync_and_get_context(uid)

        prompt = f"""
Evaluate **{character}** against the player's synced MSF.gg roster & inventory below:
{roster_text}

Give a concise, easy-to-read verdict:
1. **Verdict:** `[BUILD NOW / BUILD TO THRESHOLD / LUXURY / LEAVE ALONE]`
2. **Where They Win (Nov 2026 Meta):** Exact modes/rooms where they matter vs. where they are outdated.
3. **Exact Cost From Your Current Stats:** Gold, Training Mats, mandatory T4s/Awakened abilities (skipping luxury T4s), Gear Tier, and Iso-8 Class.
"""
        print(f"Running /build for {character} with {ACTIVE_MODEL}...")
        response = await asyncio.wait_for(
            asyncio.to_thread(
                ai_client.models.generate_content,
                model=ACTIVE_MODEL,
                contents=prompt,
                config=types.GenerateContentConfig(system_instruction=MASTER_ENGINE_PROMPT, temperature=0.2)
            ),
            timeout=30.0
        )

        embeds, _, extra_file = format_discord_output(
            f"Upgrade Advisor — {character}",
            response.text or "No upgrade analysis generated.",
            change_banner,
            discord.Color.green()
        )
        send_kwargs = {"embeds": embeds}
        if extra_file:
            send_kwargs["files"] = [extra_file]

        await interaction.followup.send(**send_kwargs)
    except Exception as exc:
        await interaction.followup.send(f"Upgrade check hit a temporary error ({exc}). Please try again in a few seconds.")
    finally:
        if extra_file:
            extra_file.close()

if __name__ == "__main__":
    bot.run(DISCORD_TOKEN)


