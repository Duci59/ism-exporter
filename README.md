# OpenSearch ISM State Exporter

**OpenSearch ISM State Exporter** là một daemon viết bằng Python, dùng để tự động thu thập trạng thái vòng đời index (Index State Management - ISM) từ các node OpenSearch và ghi lại vào một index riêng dưới dạng log.

Công cụ này giúp vượt qua hạn chế bảo mật của OpenSearch Dashboards (Vega không gọi được API hệ thống), từ đó hỗ trợ đội ngũ SIEM/NOC dễ dàng giám sát trạng thái Hot/Warm/Cold của toàn bộ cluster trên một dashboard tập trung.

---

## 🚀 Tính năng chính

### ⚡ Hiệu suất cao
- Sử dụng **Bulk API** để gom dữ liệu hàng nghìn index
- Chỉ cần **1 request duy nhất** để đẩy dữ liệu
- Giảm tải đáng kể cho cluster

### 🔐 An toàn & bảo mật
- Thông tin xác thực được lưu trong file YAML
- Hỗ trợ `verify_ssl: false` cho môi trường self-signed certificate

### 🛠 Phát hiện lỗi tự động
- Thu thập `info_message` từ ISM
- Dễ dàng phát hiện index bị lỗi (failed state)

### 🔄 Hoạt động ổn định
- Chạy dưới dạng **systemd service**
- Tự động restart khi mất kết nối

---

## 📋 Dữ liệu thu thập (Index Fields)

Dữ liệu được ghi vào index `ism-state-logs` với các field:

| Field          | Mô tả |
|----------------|------|
| `@timestamp`   | Thời gian thu thập (ISO 8601 UTC) |
| `index_name`   | Tên index |
| `policy_id`    | Policy ISM áp dụng |
| `state`        | Trạng thái hiện tại (hot, warm, cold, delete) |
| `action`       | Action đang chạy (rollover, transition...) |
| `info_message` | Thông báo hệ thống (quan trọng để debug) |

---

## 🛠 Hướng dẫn cài đặt

### 1. Yêu cầu hệ thống

- Python >= 3.8
- Thư viện:
  - `requests`
  - `pyyaml`
- OpenSearch:
  - Version 1.x hoặc 2.x
  - Có plugin ISM
- Tài khoản:
  - Quyền đọc: `_plugins/_ism/explain/*`
  - Quyền ghi: index `ism-state-logs`

---

### 2. Các bước cài đặt

#### Bước 1: Cài đặt dependencies & script

```bash
sudo pip3 install requests pyyaml
sudo cp ism_exporter.py /usr/local/bin/
sudo chmod +x /usr/local/bin/ism_exporter.py
```

#### Bước 2: Cấu hình config.yml
```bash
sudo mkdir -p /etc/ism_exporter
sudo nano /etc/ism_exporter/config.yml
```
Nội dung:
```bash
opensearch:
  url: "https://10.120.100.9:9200"
  username: "admin"
  password: "YourStrongPassword"
  target_index: "ism-state-logs"
  verify_ssl: false

exporter:
  interval_seconds: 300
```
Phân quyền bảo mật:
```bash
sudo chmod 600 /etc/ism_exporter/config.yml
```
#### Bước 3: Tạo systemd service
File: /etc/systemd/system/ism_exporter.service
```bash
[Unit]
Description=OpenSearch ISM State Exporter Daemon
After=network-online.target
Wants=network-online.target

[Service]
User=root
Type=simple
ExecStart=/usr/local/bin/ism_exporter.py --config.file=/etc/ism_exporter/config.yml
Restart=always
RestartSec=10s

[Install]
WantedBy=multi-user.target
```
Kích hoạt service
```bash
sudo systemctl daemon-reload
sudo systemctl enable ism_exporter
sudo systemctl start ism_exporter
```
## 📄 Xử lý sự cố

### ❌ HTTP 401 / 403

- Kiểm tra:
  - Username / password
  - Quyền truy cập ISM API

---

### ❌ Connection refused

- Kiểm tra:
  - URL và port (9200)
  - Firewall / network

---

### ❌ Service không start

- Lỗi argparse:
  - Đảm bảo script hỗ trợ `dest='config_file'`

### 🔍 Xem log
```bash
sudo journalctl -u ism_exporter.service -f
```