import paramiko
import os

hostname = '178.105.245.54'
username = 'root'
password = 'Danon08092001'

files_to_upload = [
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\main.py', '/root/polskibot/main.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\bot.py', '/root/polskibot/bot.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\cogs\\moderation.py', '/root/polskibot/cogs/moderation.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\database.py', '/root/polskibot/database.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\routes_config.py', '/root/polskibot/routes_config.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\run.py', '/root/polskibot/run.py'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\templates\\zarzadzanie_serwerem\\osadzenia.html', '/root/polskibot/templates/zarzadzanie_serwerem/osadzenia.html'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\templates\\glowne\\muzyka.html', '/root/polskibot/templates/glowne/muzyka.html'),
    ('c:\\Users\\danie\\Pictures\\POLSKIBOT\\templates\\glowne\\music_tokens.html', '/root/polskibot/templates/glowne/music_tokens.html')
]

print("Connecting to VPS via SSH...")
ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect(hostname, username=username, password=password)

print("Starting SFTP client...")
sftp = ssh.open_sftp()

for local_path, remote_path in files_to_upload:
    print(f"Uploading {local_path} -> {remote_path}...")
    sftp.put(local_path, remote_path)

sftp.close()
print("All files uploaded successfully!")

print("Restarting polskibot service...")
stdin, stdout, stderr = ssh.exec_command("systemctl restart polskibot")
exit_status = stdout.channel.recv_exit_status()
print(f"Service restarted. Exit code: {exit_status}")

print("Logs after restart:")
stdin, stdout, stderr = ssh.exec_command("systemctl status polskibot --no-pager")
print(stdout.read().decode('utf-8', errors='replace'))

ssh.close()
print("Done!")
