import discord
from discord.ext import commands
from discord import app_commands, Interaction, ButtonStyle
import subprocess
import json
import os
import asyncio
from discord.ui import View, Button
from datetime import datetime , UTC
import subprocess

#----------
# CONFIG
# ----------------------------
BOT_TOKEN = ""
BOT_OWNER_ID = 931439270454001695  # your Discord ID

# ----------------------------
# HELPERS
# ----------------------------
def run_cmd(cmd):
    try:
        return subprocess.check_output(cmd, text=True, stderr=subprocess.STDOUT, timeout=60)
    except subprocess.CalledProcessError as e:
        return e.output
    except Exception as e:
        return str(e)

DB_FILE = "vps_owners.json"
if not os.path.exists(DB_FILE):
    with open(DB_FILE, "w") as f:
        json.dump({}, f)

def load_db():
    with open(DB_FILE, "r") as f:
        return json.load(f)

def save_db(data):
    with open(DB_FILE, "w") as f:
        json.dump(data, f, indent=2)

async def generate_tmate_link(vps_name: str):
    run_cmd(["lxc", "exec", vps_name, "--", "rm", "-f", "/tmp/tmate.sock"])
    run_cmd([
        "lxc", "exec", vps_name, "--", "bash", "-c",
        "tmate -S /tmp/tmate.sock new-session -d; sleep 2; tmate -S /tmp/tmate.sock wait tmate-ready"
    ])
    link = run_cmd([
        "lxc", "exec", vps_name, "--", "bash", "-c",
        "tmate -S /tmp/tmate.sock display -p '#{tmate_ssh}'"
    ])
    if "lost server" in link.lower() or not link.strip():
        return None
    return link.strip()

# ----------------------------
# BOT INIT
# ----------------------------
intents = discord.Intents.default()
bot = commands.Bot(command_prefix="!", intents=intents)

# ----------------------------
# CREATE VPS COMMAND
# ----------------------------
@bot.tree.command(name="reinstall-vps", description="Reinstall your VPS with same specs (VPS owner only)")
async def reinstall_vps(interaction: discord.Interaction, vps_name: str, os_name: str = "debian"):
    # Load owners database
    try:
        with open("vps_owners.json", "r") as f:
            vps_owners = json.load(f)
    except FileNotFoundError:
        await interaction.response.send_message("❌ No VPS database found.", ephemeral=True)
        return

    # Check if VPS exists
    if vps_name not in vps_owners:
        await interaction.response.send_message("❌ VPS not found in database.", ephemeral=True)
        return

    # Check ownership
    owner_id = vps_owners[vps_name]
    if interaction.user.id != owner_id:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    await interaction.response.send_message(f"🔁 Reinstalling VPS `{vps_name}` with `{os_name}`... please wait ⏳", ephemeral=True)

    try:
        # Fetch old specs
        cpu = subprocess.getoutput(f"lxc config get {vps_name} limits.cpu").strip() or "1"
        ram = subprocess.getoutput(f"lxc config get {vps_name} limits.memory").strip() or "1GB"
        disk = subprocess.getoutput(f"lxc config device get {vps_name} root size").strip() or "4GB"

        print(f"[DEBUG] VPS {vps_name} → CPU: {cpu}, RAM: {ram}, Disk: {disk}")

        # Stop & delete old VPS
        subprocess.getoutput(f"lxc stop {vps_name} --force")
        subprocess.getoutput(f"lxc delete {vps_name} --force")

        # OS Image selector
        if os_name.lower() == "ubuntu":
            os_image = "ubuntu:22.04"
        elif os_name.lower() == "debian":
            os_image = "images:debian/12"
        else:
            os_image = "images:debian/12"  # Default

        # Recreate VPS
        subprocess.getoutput(f"lxc launch {os_image} {vps_name}")
        subprocess.getoutput(f"lxc config set {vps_name} limits.cpu {cpu}")
        subprocess.getoutput(f"lxc config set {vps_name} limits.memory {ram}")
        subprocess.getoutput(f"lxc config set {vps_name} limits.memory.enforce hard")
        subprocess.getoutput(f"lxc config device override {vps_name} root size={disk}")

        # Restart & save
        subprocess.getoutput(f"lxc start {vps_name}")
        vps_owners[vps_name] = owner_id
        with open("vps_owners.json", "w") as f:
            json.dump(vps_owners, f, indent=2)

        embed = discord.Embed(
            title="✅ VPS Reinstalled Successfully",
            description=(
                f"**VPS:** `{vps_name}`\n"
                f"**OS Image:** `{os_image}`\n"
                f"**CPU:** `{cpu}`\n"
                f"**RAM:** `{ram}`\n"
                f"**Disk:** `{disk}`\n\n"
                f"👤 Owner: <@{owner_id}>"
            ),
            color=discord.Color.green()
        )
        await interaction.followup.send(embed=embed, ephemeral=True)

    except Exception as e:
        print(f"[ERROR reinstall-vps] {e}")
        await interaction.followup.send(f"⚠️ Error reinstalling VPS:\n`{e}`", ephemeral=True)

@bot.tree.command(name="create-vps", description="Create a new VPS (Owner only)")
@app_commands.checks.has_permissions(administrator=True)
async def create_vps(interaction: Interaction, vps_name: str, cpu: int, ram: str, disk: str, owner: discord.Member):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command.", ephemeral=True)
        return

    await interaction.response.send_message(f"🚀 Creating VPS `{vps_name}` for {owner.mention}...")

    # Launch VPS
    run_cmd(["lxc", "launch", "ubuntu:22.04", vps_name])
    run_cmd(["lxc", "config", "set", vps_name, "limits.cpu", str(cpu)])
    run_cmd(["lxc", "config", "set", vps_name, "limits.memory", ram])
    run_cmd(["lxc", "config", "set", vps_name, "limits.memory.enforce", "hard"])
    run_cmd(["lxc", "config", "device", "override", vps_name, "root", f"size={disk}"])
    run_cmd(["lxc", "exec", vps_name, "--", "bash", "-c", "apt update -y && apt install -y tmate"])

    db = load_db()
    db[vps_name] = owner.id
    save_db(db)

    # DM the owner
    try:
        await owner.send(f"✅ Your VPS `{vps_name}` is ready!\nUse `/manage {vps_name}` to control it.")
    except discord.errors.HTTPException:
        await interaction.followup.send(f"⚠️ Could not DM {owner.mention}, check bot permissions.", ephemeral=True)

    await interaction.followup.send(f"VPS `{vps_name}` created successfully for {owner.mention}")

# ----------------------------
# MANAGE MENU VIEW
# ----------------------------
class ManageView(discord.ui.View):
    def __init__(self, vps_name):
        super().__init__(timeout=300)
        self.vps_name = vps_name

    def get_status_embed(self):
        output = run_cmd(["lxc", "info", self.vps_name])
        status_line = [line for line in output.splitlines() if "Status:" in line]
        status = status_line[0].replace("Status:", "").strip() if status_line else "Unknown"

        embed = discord.Embed(
            title=f"▌ VPS Management - {self.vps_name}",
            description=(
                "📊 Resource Information\n"
                f"**Status:** `{status}`\n\n"
                "🎮 Control Panel\n"
                "Use the buttons below to manage your VPS\n\n"
                f"⚡ ZatrixNodes • {datetime.now(UTC).strftime('%Y-%m-%d %H:%M:%S')}"
            ),
            color=0x00FF00 if status.lower() == "running" else 0xFF0000
        )
        return embed

    # START BUTTON
    @discord.ui.button(label="Start", style=discord.ButtonStyle.success)
    async def start_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        run_cmd(["lxc", "start", self.vps_name])
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=self.get_status_embed(),
            view=self
        )

    # STOP BUTTON
    @discord.ui.button(label="Stop", style=discord.ButtonStyle.danger)
    async def stop_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        run_cmd(["lxc", "stop", self.vps_name])
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=self.get_status_embed(),
            view=self
        )

    # RESTART BUTTON
    @discord.ui.button(label="Restart", style=discord.ButtonStyle.primary)
    async def restart_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        run_cmd(["lxc", "restart", self.vps_name])
        await interaction.followup.edit_message(
            message_id=interaction.message.id,
            embed=self.get_status_embed(),
            view=self
        )

    # TMATE BUTTON
    @discord.ui.button(label="New Tmate Link", style=discord.ButtonStyle.secondary)
    async def tmate_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        link = await generate_tmate_link(self.vps_name)
        if link:
            try:
                await interaction.user.send(
                    f"🔑 **New Tmate link for `{self.vps_name}`**:\n```\n{link}\n```"
                )
                await interaction.followup.send("✅ Tmate link sent to your DM.", ephemeral=True)
            except discord.errors.Forbidden:
                await interaction.followup.send("⚠️ Could not DM owner.", ephemeral=True)
        else:
            await interaction.followup.send("⚠️ Could not generate link.", ephemeral=True)

# ----------------------------
# MANAGE COMMAND
# ----------------------------
@bot.tree.command(name="manage", description="Manage your VPS")
async def manage(interaction: discord.Interaction, vps_name: str):
    import json, os

    DB_FILE = "vps_owners.json"
    SHARED_FILE = "vps_shared.json"

    if not os.path.exists(DB_FILE):
        await interaction.response.send_message("❌ No VPS found.", ephemeral=True)
        return

    with open(DB_FILE, "r") as f:
        db = json.load(f)

    if vps_name not in db:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return

    owner_id = db[vps_name]

    # Check if user is owner
    if interaction.user.id == owner_id:
        allowed = True
    else:
        allowed = False
        # Check if user has shared access
        if os.path.exists(SHARED_FILE):
            with open(SHARED_FILE, "r") as f:
                shared = json.load(f)
            if vps_name in shared and interaction.user.id in shared[vps_name]:
                allowed = True

    if not allowed:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    # Agar allowed, tab normal manage logic
    view = ManageView(vps_name)  
    await interaction.response.send_message(embed=view.get_status_embed(), view=view)

# ----------------------------
# LIST USER VPS
# ----------------------------
@bot.tree.command(name="list", description="List your VPS")
async def list_vps(interaction: Interaction):
    db = load_db()
    user_vps = [name for name, uid in db.items() if uid == interaction.user.id]
    if not user_vps:
        await interaction.response.send_message("❌ You don't own any VPS.", ephemeral=True)
    else:
        await interaction.response.send_message("📂 Your VPS:\n" + "\n".join(f"- `{v}`" for v in user_vps))

# ----------------------------
# ADMIN LIST
# ----------------------------
@bot.tree.command(name="adminlist", description="List all VPS (Owner only)")
async def adminlist(interaction: Interaction):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command.", ephemeral=True)
        return
    db = load_db()
    msg = "📂 All VPS:\n"
    for vps, uid in db.items():
        user = await bot.fetch_user(uid)
        msg += f"- `{vps}` (Owner: {user.mention})\n"
    await interaction.response.send_message(msg)

# ----------------------------
# DELETE VPS
# ----------------------------
@bot.tree.command(name="delete", description="Delete a VPS (Owner only)")
async def delete_vps(interaction: Interaction, vps_name: str):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command.", ephemeral=True)
        return
    run_cmd(["lxc", "delete", vps_name, "--force"])
    db = load_db()
    if vps_name in db:
        del db[vps_name]
        save_db(db)
    await interaction.response.send_message(f"🗑 VPS `{vps_name}` deleted successfully.")

@bot.tree.command(name="delete-all", description="Delete all VPS (Owner only)")
async def delete_all(interaction: discord.Interaction):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command.", ephemeral=True)
        return

    # Delete all LXC containers
    result = subprocess.run(
        "lxc list -c n --format csv | xargs -I {} lxc delete -f {}",
        shell=True,
        capture_output=True,
        text=True
    )

    # Clear the database
    db = {}
    save_db(db)

    if result.returncode == 0:
        await interaction.response.send_message("🗑 All VPS deleted successfully and database cleared.")
    else:
        await interaction.response.send_message(f"⚠️ Failed to delete VPS:\n```\n{result.stderr}\n```")

# ----------------------------
# TOTAL VPS COMMAND
# ----------------------------
@bot.tree.command(name="editvps", description="Edit VPS configuration (Bot owner only)")
@app_commands.describe(vps_name="VPS ka naam", ram="New RAM (e.g. 2GB)", disk="New Disk (e.g. 20GB)", cpu="New CPU cores (e.g. 2)")
async def editvps(interaction: discord.Interaction, vps_name: str, ram: str, disk: str, cpu: str):
    # ✅ Only bot owner can use this
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command!", ephemeral=True)
        return

    try:
        # ✅ Update RAM & CPU
        subprocess.run(["lxc", "config", "set", vps_name, "limits.memory", ram], check=True)
        subprocess.run(["lxc", "config", "set", vps_name, "limits.cpu", cpu], check=True)

        # ✅ Update disk size safely
        # Check if root device exists
        check = subprocess.run(["lxc", "config", "device", "show", vps_name], capture_output=True, text=True)
        if "root:" in check.stdout:
            subprocess.run(["lxc", "config", "device", "set", vps_name, "root", "size", disk], check=True)
        else:
            subprocess.run(["lxc", "config", "device", "add", vps_name, "root", "disk", f"path=/" , f"size={disk}"], check=True)

        # ✅ Send confirmation
        embed = discord.Embed(
            title="✅ VPS Configuration Updated",
            description=(
                f"**VPS:** `{vps_name}`\n"
                f"**RAM:** `{ram}`\n"
                f"**Disk:** `{disk}`\n"
                f"**CPU:** `{cpu}`"
            ),
            color=0x00FF00
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    except subprocess.CalledProcessError as e:
        await interaction.response.send_message(f"⚠️ Command failed:\n```{e}```", ephemeral=True)

@bot.tree.command(name="totalvps", description="Show total number of VPS (Owner only)")
async def totalvps(interaction: Interaction):
    if interaction.user.id != BOT_OWNER_ID:
        await interaction.response.send_message("❌ Only bot owner can use this command.", ephemeral=True)
        return

    db = load_db()
    total = len(db)
    await interaction.response.send_message(f"📊 Total VPS: {total}")

@bot.tree.command(name="exec-vps", description="Execute a command inside your VPS")
async def exec_vps(interaction: discord.Interaction, vps_name: str, command: str):
    db = load_db()
    
    # Check if VPS exists
    if vps_name not in db:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return

    # Check if the user is the owner
    if db[vps_name] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    await interaction.response.defer(ephemeral=True)  # Defer to allow long commands

    try:
        result = subprocess.run(
            ["lxc", "exec", vps_name, "--", "bash", "-c", command],
            capture_output=True,
            text=True,
            timeout=60
        )
        output = result.stdout.strip() or result.stderr.strip()
        if len(output) > 1900:  # Discord message limit
            output = output[:1900] + "\n...output truncated..."
        await interaction.followup.send(f"📥 Output of `{command}` in `{vps_name}`:\n```\n{output}\n```", ephemeral=True)
    except subprocess.TimeoutExpired:
        await interaction.followup.send("⚠️ Command timed out.", ephemeral=True)
    except Exception as e:
        await interaction.followup.send(f"⚠️ Error executing command: {e}", ephemeral=True)

@bot.tree.command(name="report", description="Report an issue with your VPS")
async def report(interaction: Interaction, vps_name: str, issue: str):
    import json, os
    from discord import ui, ButtonStyle, Embed

    BOT_OWNER_ID = 931439270454001695
    DB_FILE = "vps_owners.json"

    # Load VPS DB
    if not os.path.exists(DB_FILE):
        await interaction.response.send_message("❌ No VPS database found.", ephemeral=True)
        return

    with open(DB_FILE, "r") as f:
        db = json.load(f)

    # Check if VPS exists
    if vps_name not in db:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return

    # Check if reporter owns the VPS
    if db[vps_name] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    # Embed to send to bot owner
    embed = Embed(title=f"📝 VPS Report: {vps_name}", color=0x00ff00)
    embed.add_field(name="Reporter", value=interaction.user.mention)
    embed.add_field(name="Issue", value=issue)

    # Modal for bot owner to reply
    class ReplyModal(ui.Modal, title="Reply to Reporter"):
        def __init__(self, reporter_id):
            super().__init__()
            self.reporter_id = reporter_id
            self.add_item(ui.TextInput(label="Reply to reporter", style=discord.TextStyle.long))

        async def on_submit(self, modal_interaction):
            reporter = await interaction.client.fetch_user(self.reporter_id)
            try:
                await reporter.send(f"📨 Reply from VPS Owner:\n{self.children[0].value}")
                await modal_interaction.response.send_message("✅ Reply sent!", ephemeral=True)
            except:
                await modal_interaction.response.send_message("⚠️ Could not send reply.", ephemeral=True)

    # Button view
    class ReplyView(ui.View):
        def __init__(self, reporter_id):
            super().__init__(timeout=None)
            self.reporter_id = reporter_id

        @ui.button(label="Reply to Reporter", style=ButtonStyle.primary)
        async def reply_button(self, button_interaction, button):
            await button_interaction.response.send_modal(ReplyModal(self.reporter_id))

    # Send report to bot owner
    bot_owner = await bot.fetch_user(BOT_OWNER_ID)
    await bot_owner.send(embed=embed, view=ReplyView(interaction.user.id))

    await interaction.response.send_message(f"✅ Your report for `{vps_name}` has been sent to the bot owner.", ephemeral=True)

@bot.tree.command(name="share-vps", description="Share your VPS access with another user")
async def share_vps(interaction: discord.Interaction, vps_name: str, user: discord.User):
    import json, os

    DB_FILE = "vps_owners.json"
    SHARED_FILE = "vps_shared.json"

    if not os.path.exists(DB_FILE):
        await interaction.response.send_message("❌ No VPS database found.", ephemeral=True)
        return

    with open(DB_FILE, "r") as f:
        db = json.load(f)

    if vps_name not in db:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return

    if db[vps_name] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    if not os.path.exists(SHARED_FILE):
        with open(SHARED_FILE, "w") as f:
            json.dump({}, f)

    with open(SHARED_FILE, "r") as f:
        shared = json.load(f)

    if vps_name not in shared:
        shared[vps_name] = []

    if user.id in shared[vps_name]:
        await interaction.response.send_message(f"⚠️ {user.mention} already has access to `{vps_name}`.", ephemeral=True)
        return

    shared[vps_name].append(user.id)
    with open(SHARED_FILE, "w") as f:
        json.dump(shared, f, indent=2)

    await interaction.response.send_message(f"✅ {user.mention} now has access to `{vps_name}`.", ephemeral=True)

@bot.tree.command(name="rshare-vps", description="Remove shared VPS access from a user")
async def rshare_vps(interaction: discord.Interaction, vps_name: str, user: discord.User):
    import json, os

    DB_FILE = "vps_owners.json"
    SHARED_FILE = "vps_shared.json"

    if not os.path.exists(DB_FILE):
        await interaction.response.send_message("❌ No VPS database found.", ephemeral=True)
        return

    with open(DB_FILE, "r") as f:
        db = json.load(f)

    if vps_name not in db:
        await interaction.response.send_message("❌ VPS not found.", ephemeral=True)
        return

    if db[vps_name] != interaction.user.id:
        await interaction.response.send_message("❌ You are not the owner of this VPS.", ephemeral=True)
        return

    if not os.path.exists(SHARED_FILE):
        await interaction.response.send_message("⚠️ No shared VPS found.", ephemeral=True)
        return

    with open(SHARED_FILE, "r") as f:
        shared = json.load(f)

    if vps_name not in shared or user.id not in shared[vps_name]:
        await interaction.response.send_message(f"⚠️ {user.mention} does not have access to `{vps_name}`.", ephemeral=True)
        return

    shared[vps_name].remove(user.id)
    with open(SHARED_FILE, "w") as f:
        json.dump(shared, f, indent=2)

    await interaction.response.send_message(f"✅ {user.mention}'s access to `{vps_name}` has been removed.", ephemeral=True)

@bot.tree.command(name="share-list", description="List all shared VPS accesses")
async def share_list(interaction: discord.Interaction):
    import json, os

    SHARED_FILE = "vps_shared.json"
    if not os.path.exists(SHARED_FILE):
        await interaction.response.send_message("❌ No VPS has been shared yet.", ephemeral=True)
        return

    with open(SHARED_FILE, "r") as f:
        shared = json.load(f)

    if not shared:
        await interaction.response.send_message("❌ No VPS has been shared yet.", ephemeral=True)
        return

    msg = "📂 Shared VPS List:\n"
    for vps, user_ids in shared.items():
        if user_ids:
            users = []
            for uid in user_ids:
                try:
                    u = await bot.fetch_user(uid)
                    users.append(u.mention)
                except:
                    users.append(f"<@{uid}>")
            msg += f"- `{vps}`: {', '.join(users)}\n"

    await interaction.response.send_message(msg, ephemeral=True)

# ----------------------------
# ON READY
# ----------------------------
@bot.event
async def on_ready():
    await bot.tree.sync()
    print(f"✅ Logged in as {bot.user}")

bot.run(BOT_TOKEN)