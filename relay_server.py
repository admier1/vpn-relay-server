import os
import subprocess
import requests
import json
import logging
import http.client as http_client
import sys
import time

# Setup logging
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# Enable HTTP connection logging for requests
http_client.HTTPConnection.debuglevel = 1
requests_log = logging.getLogger("requests.packages.urllib3")
requests_log.setLevel(logging.DEBUG)
requests_log.propagate = True

UPDATE_INTERVAL = 300  # Time interval between update checks in seconds (5 minutes)
STATUS_UPDATE_INTERVAL = 60  # Time interval between status updates in seconds (1 minute)
CENTRAL_NODE_URL = "http://relay.brinxai.com:5002"

def check_for_updates():
    try:
        logger.debug("Checking for updates...")
        output = subprocess.check_output(['git', 'pull', 'origin', 'main'])
        
        if b'Already up to date.' not in output:
            logger.debug("Updates detected. Restarting the script.")
            restart_script()
        else:
            logger.debug("No updates found. Continuing with the current version.")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to check for updates: {e}")

def restart_script():
    try:
        logger.info("Restarting script...")
        python = sys.executable
        os.execl(python, python, *sys.argv)
    except Exception as e:
        logger.error(f"Failed to restart script: {e}")
        sys.exit(1)

def get_server_ip():
    try:
        ip = requests.get('http://whatismyip.akamai.com/').text.strip()
        logger.debug(f"Retrieved server IP: {ip}")
        return ip
    except requests.RequestException as e:
        logger.error(f"Failed to get server IP: {e}")
        return None

def check_node_ip_exists(server_ip):
    try:
        response = requests.get(f"{CENTRAL_NODE_URL}/vpn_list")
        response.raise_for_status()
        nodes = response.json()
        for node in nodes:
            if node['node_ip'] == server_ip:
                logger.debug(f"Node IP {server_ip} found in the database.")
                return True, node['id']
        logger.debug(f"Node IP {server_ip} not found in the database.")
        return False, None
    except requests.RequestException as e:
        logger.error(f"Failed to check if node IP exists: {e}")
        return False, None

def retrieve_existing_ovpn(node_id):
    try:
        response = requests.get(f"{CENTRAL_NODE_URL}/download_vpn/{node_id}")
        response.raise_for_status()
        data = response.json()
        ovpn_file = data.get('ovpn_file')
        logger.debug(f"Retrieved existing .ovpn file with content length: {len(ovpn_file) if ovpn_file else 0}")
        return ovpn_file
    except requests.RequestException as e:
        logger.error(f"Failed to retrieve existing .ovpn file: {e}")
        return None

def initialize_pki():
    try:
        logger.debug("Initializing PKI directory")
        subprocess.check_call(['easyrsa', 'init-pki'])
        logger.debug("PKI directory initialized successfully")
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to initialize PKI directory: {e}")
        return False
    return True

def generate_ovpn_file():
    try:
        if not os.path.exists('/etc/openvpn/pki'):
            if not initialize_pki():
                return None
        
        logger.debug("Generating .ovpn file")
        subprocess.check_call(['easyrsa', 'build-client-full', 'client1', 'nopass'])
        
        ovpn_file_path = '/etc/openvpn/client1.ovpn'
        with open(ovpn_file_path, 'w') as ovpn_file:
            subprocess.check_call(['ovpn_getclient', 'client1'], stdout=ovpn_file)
        
        with open(ovpn_file_path, 'r') as ovpn_file:
            content = ovpn_file.read()
            logger.debug(f".ovpn file generated successfully, content length: {len(content)}")
            return content
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to generate .ovpn file: {e}")
        return None
    except FileNotFoundError as e:
        logger.error(f"Error: {e}")
        return None

def send_ovpn_file(server_ip, ovpn_file_content):
    logger.debug(f"Preparing to send .ovpn file to central node. File content preview: {ovpn_file_content[:100]}...")
    payload = {
        "node_ip": server_ip,
        "ovpn_file": ovpn_file_content
    }
    try:
        headers = {"Content-Type": "application/json"}
        response = requests.post(f"{CENTRAL_NODE_URL}/submit_vpn", headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        logger.debug(f"Successfully sent .ovpn file. Server responded with status code: {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to send .ovpn file: {e}")

def check_openvpn_status():
    try:
        logger.debug("Checking OpenVPN status")
        status_output = subprocess.check_output(['pgrep', '-x', 'openvpn']).strip()
        status = "Active" if status_output else "Inactive"
        logger.debug(f"OpenVPN status: {status}")
        return status
    except subprocess.CalledProcessError as e:
        logger.error(f"Failed to check OpenVPN status: {e}")
        return "Inactive"

def send_status_update(server_ip, status):
    payload = {
        "node_ip": server_ip,
        "status": status
    }
    try:
        headers = {"Content-Type": "application/json"}
        response = requests.post(f"{CENTRAL_NODE_URL}/update_status", headers=headers, data=json.dumps(payload))
        response.raise_for_status()
        logger.debug(f"Successfully sent status update. Server responded with status code: {response.status_code}")
    except requests.RequestException as e:
        logger.error(f"Failed to send status update: {e}")

def main():
    logger.info("Starting VPN setup process")
    server_ip = get_server_ip()
    
    if server_ip:
        node_exists, node_id = check_node_ip_exists(server_ip)
        
        if node_exists:
            existing_ovpn = retrieve_existing_ovpn(node_id)
            new_ovpn_content = generate_ovpn_file()
            
            if new_ovpn_content:
                if not existing_ovpn or existing_ovpn != new_ovpn_content:
                    send_ovpn_file(server_ip, new_ovpn_content)
                    logger.info("New or updated .ovpn file sent.")
                else:
                    logger.info("Existing .ovpn file is up-to-date. No need to send.")
            else:
                logger.error("Failed to generate .ovpn file. Exiting.")
        else:
            logger.info(f"Node IP {server_ip} not found in the database. Retrying in {UPDATE_INTERVAL} seconds.")
    else:
        logger.error("Failed to get server IP. Exiting.")

if __name__ == '__main__':
    server_ip = get_server_ip()
    if server_ip:
        while True:
            check_for_updates()  # Check for updates
            main()  # Run the main script logic
            status = check_openvpn_status()  # Check OpenVPN status
            send_status_update(server_ip, status)  # Send status update to the central server
            logger.debug(f"Sleeping for {STATUS_UPDATE_INTERVAL} seconds before next status update.")
            time.sleep(STATUS_UPDATE_INTERVAL)
