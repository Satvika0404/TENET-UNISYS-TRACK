import argparse
import random
import time
from datetime import datetime
import requests

def clamp01(x):
    return max(0.0, min(1.0, x))

def make_resource_set():
    resources = []
    for i in range(3):
        resources.append(("edge", f"edge-{i+1}"))
    for i in range(3):
        resources.append(("cloud", f"cloud-{i+1}"))
    for i in range(2):
        resources.append(("gpu", f"gpu-{i+1}"))
    return resources

def step_point(rtype, rid):
    base_rtt = {"edge": 20, "cloud": 80, "gpu": 60}[rtype]
    price = {"edge": 0.0, "cloud": random.uniform(0.05, 0.20), "gpu": random.uniform(0.40, 1.20)}[rtype]
    reliability = {"edge": random.uniform(0.93, 0.98), "cloud": random.uniform(0.97, 0.995), "gpu": random.uniform(0.96, 0.992)}[rtype]
    power = {"edge": random.uniform(15, 60), "cloud": random.uniform(80, 200), "gpu": random.uniform(180, 350)}[rtype]

    cpu = clamp01(random.gauss(0.45, 0.20))
    mem = clamp01(random.gauss(0.50, 0.18))
    gpu = clamp01(random.gauss(0.55, 0.25)) if rtype == "gpu" else 0.0

    if random.random() < 0.08:
        cpu = clamp01(cpu + random.uniform(0.25, 0.45))
        mem = clamp01(mem + random.uniform(0.20, 0.40))
        if rtype == "gpu":
            gpu = clamp01(gpu + random.uniform(0.30, 0.55))

    rtt = max(1.0, random.gauss(base_rtt, base_rtt * 0.25))
    bw = max(5.0, random.gauss(120 if rtype != "edge" else 80, 25))

    return {
        "ts": datetime.utcnow().isoformat(),
        "resource_id": rid,
        "resource_type": rtype,
        "cpu_util": cpu,
        "mem_util": mem,
        "gpu_util": gpu,
        "net_rtt_ms": rtt,
        "net_bw_mbps": bw,
        "price_per_hour_usd": price,
        "reliability": reliability,
        "power_w": power,
        "extra": {"demo": True},
    }

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", default="http://127.0.0.1:8000/telemetry")
    ap.add_argument("--seconds", type=int, default=60)
    ap.add_argument("--hz", type=float, default=2.0)
    args = ap.parse_args()

    resources = make_resource_set()
    end = time.time() + args.seconds
    period = 1.0 / max(0.1, args.hz)

    print(f"Sending telemetry to {args.url} for {args.seconds}s ...")
    while time.time() < end:
        for rtype, rid in resources:
            p = step_point(rtype, rid)
            try:
                requests.post(args.url, json=p, timeout=2.0)
            except Exception as e:
                print("telemetry send failed:", e)
        time.sleep(period)

    print("done")

if __name__ == "__main__":
    main()
