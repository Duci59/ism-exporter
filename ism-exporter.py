#!/usr/bin/env python3
import requests
import json
import time
import yaml
import argparse
import logging
from datetime import datetime, timezone
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

logging.basicConfig(
    level=logging.INFO,
    format='%(levelname)s: %(message)s'
)

def load_config(config_path):
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        logging.error(f"Không thể đọc file cấu hình: {e}")
        exit(1)

def get_ism_states(os_config):
    """Lấy thông tin Index State Management"""
    try:
        url = f"{os_config['url']}/_plugins/_ism/explain/*"
        auth = (os_config['username'], os_config['password'])
        response = requests.get(url, auth=auth, verify=os_config.get('verify_ssl', False), timeout=10)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logging.error(f"Lỗi khi gọi API ISM: {e}")
        return {}

def get_indices_health(os_config):
    """Lấy trạng thái Green/Yellow/Red của tất cả các Index"""
    try:
        url = f"{os_config['url']}/_cluster/health?level=indices"
        auth = (os_config['username'], os_config['password'])
        response = requests.get(url, auth=auth, verify=os_config.get('verify_ssl', False), timeout=10)
        response.raise_for_status()
        return response.json().get('indices', {})
    except Exception as e:
        logging.error(f"Lỗi khi gọi API Cluster Health: {e}")
        return {}

def get_unassigned_reasons(os_config):
    """Quét và lấy lý do lỗi (Allocation Explain) của tất cả các shard bị Unassigned"""
    try:
        url = f"{os_config['url']}/_cat/shards?h=index,state,unassigned.reason,unassigned.details&format=json"
        auth = (os_config['username'], os_config['password'])
        response = requests.get(url, auth=auth, verify=os_config.get('verify_ssl', False), timeout=10)
        response.raise_for_status()
        shards = response.json()

        reasons = {}
        for shard in shards:
            if shard.get('state') == 'UNASSIGNED':
                idx = shard.get('index')
                reason = shard.get('unassigned.reason', 'UNKNOWN')
                details = shard.get('unassigned.details', '')
                msg = f"[{reason}] {details}"

                # Gom nhóm các lỗi nếu index có nhiều shard bị lỗi
                if idx in reasons and msg not in reasons[idx]:
                    reasons[idx] += f" | {msg}"
                else:
                    reasons[idx] = msg
        return reasons
    except Exception as e:
        logging.error(f"Lỗi khi lấy Allocation Explain (Cat Shards): {e}")
        return {}

def push_to_opensearch(bulk_data, os_config):
    try:
        url = f"{os_config['url']}/_bulk"
        auth = (os_config['username'], os_config['password'])
        headers = {"Content-Type": "application/x-ndjson"}
        response = requests.post(url, auth=auth, verify=os_config.get('verify_ssl', False), headers=headers, data=bulk_data)
        response.raise_for_status()
        logging.info(f"Đã đẩy dữ liệu thành công. HTTP Status: {response.status_code}")
    except Exception as e:
        logging.error(f"Lỗi khi đẩy dữ liệu vào OpenSearch: {e}")

def process_and_push(config):
    os_config = config['opensearch']

    # 1. Thu thập dữ liệu từ 3 nguồn API
    ism_data = get_ism_states(os_config) or {}
    indices_health = get_indices_health(os_config) or {}
    unassigned_reasons = get_unassigned_reasons(os_config) or {}

    if not indices_health and not ism_data:
        logging.warning("Không lấy được dữ liệu Health và ISM.")
        return

    bulk_payload = ""
    current_timestamp = datetime.now(timezone.utc).isoformat()
    target_index = os_config.get('target_index', 'index-monitoring-logs') # Đổi tên mặc định cho phù hợp

    # 2. Lấy danh sách toàn bộ index (Gộp từ Health và ISM)
    all_indices = set(indices_health.keys()).union(set(ism_data.keys()))

    for index_name in all_indices:
        # Tùy chọn: Bỏ qua các index hệ thống (bắt đầu bằng dấu chấm) để bớt rác log
        if index_name.startswith('.'):
            continue

        i_health = indices_health.get(index_name, {})
        i_ism = ism_data.get(index_name, {})
        if not isinstance(i_ism, dict):
            i_ism = {}

        # Xử lý dữ liệu Health & Lỗi
        health_status = i_health.get("status", "unknown")
        # Chuyển đổi mã màu sang số để dễ vẽ biểu đồ (Green=0, Yellow=1, Red=2)
        health_code = 0 if health_status == 'green' else (1 if health_status == 'yellow' else (2 if health_status == 'red' else -1))
        unassigned_shards = i_health.get("unassigned_shards", 0)
        allocation_explanation = unassigned_reasons.get(index_name, "N/A")

        # Xử lý dữ liệu ISM
        policy_id = i_ism.get("policy_id") or i_ism.get("index.policy_id") or i_ism.get("index.plugins.index_state_management.policy_id") or "N/A"
        ism_state = i_ism.get("state", {}).get("name", "N/A")
        ism_action = i_ism.get("action", {}).get("name", "N/A")
        ism_info_message = i_ism.get("info", {}).get("message", "N/A")

        # 3. Đóng gói Document
        doc = {
            "@timestamp": current_timestamp,
            "index_name": index_name,
            "health_status": health_status,
            "health_code": health_code,
            "unassigned_shards": unassigned_shards,
            "allocation_explanation": allocation_explanation,
            "policy_id": policy_id,
            "ism_state": ism_state,
            "ism_action": ism_action,
            "ism_info_message": ism_info_message
        }

        action_meta = { "index": { "_index": target_index } }
        bulk_payload += json.dumps(action_meta) + "\n"
        bulk_payload += json.dumps(doc) + "\n"

    if bulk_payload:
        push_to_opensearch(bulk_payload, os_config)
    else:
        logging.info("Không có dữ liệu index nào để đẩy.")

def main():
    parser = argparse.ArgumentParser(description='OpenSearch Index & ISM Monitor')

    parser.add_argument('--config.file', dest='config_file', default='/etc/ism_exporter/config.yml', help='Đường dẫn tới file cấu hình YAML')
    args = parser.parse_args()

    config = load_config(args.config_file)
    interval = config.get('exporter', {}).get('interval_seconds', 300)

    logging.info(f"Khởi động OpenSearch Monitor. Đang lấy dữ liệu mỗi {interval} giây...")

    while True:
        process_and_push(config)
        time.sleep(interval)

if __name__ == "__main__":
    main()
