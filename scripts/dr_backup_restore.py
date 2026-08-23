import os
import subprocess
import time
import argparse
from datetime import datetime

DB_USER = os.environ.get("POSTGRES_USER", "orion_admin")
DB_NAME = os.environ.get("POSTGRES_DB", "keycloak")
BACKUP_DIR = os.environ.get("BACKUP_DIR", "./backups")

def create_backup():
    if not os.path.exists(BACKUP_DIR):
        os.makedirs(BACKUP_DIR)
        
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_file = os.path.join(BACKUP_DIR, f"orion_backup_{timestamp}.sql")
    
    print(f"[*] Starting Database Backup -> {backup_file}")
    start_time = time.time()
    
    # We execute pg_dump inside the docker container to avoid needing local pg_tools
    cmd = f"docker exec orion-postgres pg_dump -U {DB_USER} -F c {DB_NAME} > {backup_file}"
    
    try:
        subprocess.run(cmd, shell=True, check=True)
        duration = time.time() - start_time
        file_size = os.path.getsize(backup_file) / (1024 * 1024)
        print(f"[+] Backup Successful! Time taken: {duration:.2f} seconds.")
        print(f"[+] File Size: {file_size:.2f} MB")
        return backup_file
    except subprocess.CalledProcessError as e:
        print(f"[-] Backup Failed!")
        return None

def restore_backup(backup_file):
    print(f"[*] Starting Database Restore <- {backup_file}")
    start_time = time.time()
    
    # We pipe the local backup file into pg_restore inside the container
    cmd = f"docker exec -i orion-postgres pg_restore -U {DB_USER} -d {DB_NAME} -c -1 < {backup_file}"
    
    try:
        subprocess.run(cmd, shell=True, check=True)
        duration = time.time() - start_time
        print(f"[+] Restore Successful! Time taken: {duration:.2f} seconds.")
        print(f"[+] RTO (Recovery Time Objective) measured at: {duration:.2f} seconds.")
        return True
    except subprocess.CalledProcessError as e:
        print(f"[-] Restore Failed!")
        return False

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="ORION Disaster Recovery Drill Script")
    parser.add_argument("--drill", action="store_true", help="Run a full backup and immediately restore it to measure RTO")
    args = parser.parse_args()
    
    if args.drill:
        print("=== ORION Disaster Recovery Drill ===")
        b_file = create_backup()
        if b_file:
            time.sleep(2) # Brief pause
            restore_backup(b_file)
