#!/usr/bin/env bash
# Chạy bench_v2 (DialSTART + agentic_v3 ở tag bench-freeze-v2) theo thứ tự ưu tiên.
#
#   bash eval/bench/run_bench_v2.sh m2    # arm chính, 40 cuộc họp (dev + held-out)
#   bash eval/bench/run_bench_v2.sh m3    # ablation phụ, 30 cuộc họp dev, dừng khi chạm trần
#
# Chạy lại đúng lệnh thì run.py dùng lại output có sẵn và chỉ chạy cuộc họp còn thiếu/lỗi.
# Trần $8,04 là của CẢ nghiên cứu (cộng spend_ledger.jsonl); 3134 lời gọi Decisions của các run
# trước khi có giá ước $0,0001/lời gọi (đo được ~$0,00006).
# Không chép output nào từ bench_v1: run đó chạy trên cây làm việc bẩn nên không biết chắc mã nào
# đã sinh ra nó; mọi arm ở đây cùng một phiên bản mã (manifest ghi git sha, git_dirty).
set -euo pipefail
cd "$(dirname "$0")/../.."

PY=../.venv/bin/python
RUN=bench_v2
BENCH=(--run "$RUN" --budget-usd 8.04 --unpriced-call-usd 0.0001)

arm() {  # arm <tên> <split> [repeat]
    echo "=== $(date +%H:%M:%S) $1 split=$2 repeat=${3:-1}"
    "$PY" eval/bench/run.py "${BENCH[@]}" --arm "$1" --split "$2" --repeat "${3:-1}"
}

case "${1:-}" in
    m2)
        arm v3 all
        arm b0_single_prompt all
        arm verif_keep all
        arm verif_drop all
        arm v3_oracle dev
        arm judge_off all
        for r in 1 2 3; do arm b1_extractors_only all "$r"; done
        ;;
    m3)
        arm seg_none dev
        arm seg_treeseg dev
        arm consensus_1 dev
        arm verif_samemodel dev
        arm tools_0 dev
        ;;
    *)
        echo "dùng: $0 m2|m3" >&2
        exit 2
        ;;
esac
