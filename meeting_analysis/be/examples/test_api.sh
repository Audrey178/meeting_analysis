#!/usr/bin/env bash
# Gọi thử API v3 với các file ví dụ trong thư mục này (cần server đang chạy, Redis, gateway LLM).
#
#   uvicorn --app-dir be main:app                  # từ thư mục meeting_analysis/
#   bash be/examples/test_api.sh                   # mặc định http://localhost:8000
#   API=http://host:8000 bash be/examples/test_api.sh
#   S3=1 bash be/examples/test_api.sh              # thêm bước đọc transcript từ source.transcript_uri:
#                                                  # tải transcript.json lên s3://meetings/MTG-DEMO-001/transcript.json
#                                                  # (boto3; MinIO: đặt AWS_ENDPOINT_URL + AWS_ACCESS_KEY_ID/SECRET)
#
# Response lưu ở $OUT (mặc định /tmp/meeting-api-test). Lần đầu POST /content chạy cả pipeline (LLM) nên lâu;
# POST /tasks, /decisions sau đó lấy kết quả tính nền từ cache.

set -uo pipefail

API=${API:-http://localhost:8000}
OUT=${OUT:-/tmp/meeting-api-test}
PYTHON=${PYTHON:-python}
HERE=$(cd "$(dirname "$0")" && pwd)
MEETING_ID=MTG-DEMO-001
mkdir -p "$OUT"
failures=0

# call <name> <method> <path> <expected status> [body file]: gọi API, lưu response, kiểm mã HTTP.
call() {
  local name=$1 method=$2 path=$3 expected=$4 body=${5:-}
  local args=(-sS -o "$OUT/$name.json" -w "%{http_code}" --max-time 1800 -X "$method" "$API$path")
  [[ -n $body ]] && args+=(-H "Content-Type: application/json" --data-binary "@$body")
  local status
  status=$(curl "${args[@]}")
  if [[ $status == "$expected" ]]; then
    echo "PASS $method $path -> $status ($OUT/$name.json)"
  else
    echo "FAIL $method $path -> $status, mong đợi $expected: $(head -c 300 "$OUT/$name.json" 2>/dev/null)"
    failures=$((failures + 1))
    return 1
  fi
}

# expect_type <name> <document_type>: kiểm document_type và in số phần tử của data.
expect_type() {
  local name=$1 type=$2 got
  got=$(jq -r '.document_type' "$OUT/$name.json" 2>/dev/null || true)
  if [[ $got == "$type" ]]; then
    echo "     $type: $(jq -c '.data | to_entries | map({(.key): (.value | length)}) | add' "$OUT/$name.json"), status=$(jq -r '.generation.status' "$OUT/$name.json")"
  else
    echo "FAIL $name: document_type '$got', mong đợi '$type'"
    failures=$((failures + 1))
  fi
}

call health GET /health 200

# Luồng chính: transcript gửi kèm (items).
call post_content POST /v3/meetings/content 200 "$HERE/test.request.json" && expect_type post_content meeting_content
call post_tasks POST /v3/meetings/tasks 200 "$HERE/test.request.json" && expect_type post_tasks meeting_tasks
call post_decisions POST /v3/meetings/decisions 200 "$HERE/test.request.json" && expect_type post_decisions meeting_decisions

# Lấy lại theo meeting_id (request POST /content gần nhất).
call get_content GET "/v3/meetings/content/$MEETING_ID" 200 && expect_type get_content meeting_content
call get_tasks GET "/v3/meetings/tasks/$MEETING_ID" 200 && expect_type get_tasks meeting_tasks
call get_decisions GET "/v3/meetings/decisions/$MEETING_ID" 200 && expect_type get_decisions meeting_decisions

# Lỗi: không có items lẫn transcript_uri -> 422; cuộc họp chưa gọi POST /content -> 404.
jq 'del(.items) | .source.transcript_uri = null' "$HERE/test.request.json" > "$OUT/no_transcript.request.json"
call error_no_transcript POST /v3/meetings/content 422 "$OUT/no_transcript.request.json"
call error_unknown_meeting GET /v3/meetings/tasks/MTG-KHONG-CO 404

# Tuỳ chọn: transcript đọc từ source.transcript_uri (request post_content.request.json không có items).
if [[ ${S3:-0} == 1 ]]; then
  "$PYTHON" -c "import boto3, sys; boto3.client('s3').upload_file(sys.argv[1], 'meetings', 'MTG-DEMO-001/transcript.json')" \
    "$HERE/transcript.json"
  echo "     đã tải transcript.json lên s3://meetings/MTG-DEMO-001/transcript.json"
  call s3_content POST /v3/meetings/content 200 "$HERE/post_content.request.json" && expect_type s3_content meeting_content
fi

echo
if ((failures)); then
  echo "$failures bước FAIL"
  exit 1
fi
echo "Tất cả PASS"
