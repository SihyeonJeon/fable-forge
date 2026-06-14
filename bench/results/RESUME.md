# SWE-bench gate-ON vs gate-OFF — run state (paused)

Paused mid-way through a SWE-bench Pro batch. The 30-instance result below is **saved
and final**; the remaining 8 Pro instances were in-flight (no per-instance checkpoint)
so they must be regenerated on resume.

## Confirmed so far (gate OFF = naked opus, gate ON = forge opus, same model)

| benchmark | naked | gated | delta |
| --- | --- | --- | --- |
| SWE-bench Verified slice (light repos, N=28) | 22/28 | 23/28 | +1 |
| SWE-bench Pro (qutebrowser, N=2) | 1/2 | 2/2 | +1 |
| **combined (N=30)** | **23/30** | **25/30** | **+2, zero regressions** |

Gate never lost an instance naked solved; it won two that naked failed
(Verified `pytest-10051`, Pro `parse_duration`), both because the spec/acceptance
discipline made opus match the exact test contract instead of a plausible-but-wrong
shortcut. Token cost gate ON ≈ 2–3× naked.

## Durable artifacts (survive reboot)
- Scripts (repo): `bench/swebench_forge.py` (Verified gen), `bench/swebenchpro_forge.py`
  (Pro gen), `bench/swebench_plot.py` (graph).
- Results (repo): `bench/results/verified/*`, `bench/results/pro/*`.
- Graph: `assets/swebench_slice.png` (Verified N=28).
- Docker images: 10 `jefzda/sweap-images:*` Pro images (incl. the 8 already pulled).

## Ephemeral (in /tmp — gone after reboot, regenerable)
- venv `/tmp/swe_venv` (python3.14 + swebench pandas tqdm docker matplotlib datasets)
- `/tmp/swe` (Verified working dir, local dataset `/tmp/swe/swe_ds`)
- `/tmp/swepro` (Pro working dir), `/tmp/swe/SWE-bench_Pro-os` (Pro harness clone)

## To resume the 8 pending Pro instances
Pending ids: `bench/results/pro/batch2_pending_ids.json` (8 qutebrowser).

1. If /tmp was cleared, recreate venv + harness:
   ```
   /opt/homebrew/bin/python3 -m venv /tmp/swe_venv
   /tmp/swe_venv/bin/pip install swebench pandas tqdm docker matplotlib datasets
   git clone https://github.com/scaleapi/SWE-bench_Pro-os /tmp/swe/SWE-bench_Pro-os
   mkdir -p /tmp/swepro && cp bench/results/pro/{patches_naked.json,patches_gated.json,meta.json,samples.csv} /tmp/swepro/
   python3 -c "import json;json.dump([json.loads(open('/tmp/swepro/samples.csv').read())],open('/tmp/swepro/samples.json','w'))"  # or rebuild samples.json from CSV
   ```
2. Generate (machine awake + online; uses `claude` CLI = your Claude plan quota):
   ```
   IDS=$(python3 -c "import json;print(','.join(json.load(open('bench/results/pro/batch2_pending_ids.json'))))")
   /tmp/swe_venv/bin/python bench/swebenchpro_forge.py --ids "$IDS" --model opus
   ```
3. Pull images if Docker was pruned (else skip — they persist):
   tags = `jefzda/sweap-images:<dockerhub_tag>` for each id (from the HF dataset).
4. Eval (offline OK; emulated amd64 on Apple Silicon):
   ```
   cd /tmp/swe/SWE-bench_Pro-os
   for arm in naked gated; do /tmp/swe_venv/bin/python swe_bench_pro_eval.py \
     --raw_sample_path /tmp/swepro/samples.csv --patch_path /tmp/swepro/patches_$arm.json \
     --output_dir /tmp/swepro/out_$arm --dockerhub_username jefzda \
     --scripts_dir run_scripts --use_local_docker --docker_platform linux/amd64; done
   ```
5. Re-plot (point `swebench_plot.py` at the combined reports) and update README/BENCHMARK.

## Note
Nothing here is committed yet. To protect the results across a `git clean`, run
`git add bench/ assets/swebench_slice.png && git commit` before walking away.
