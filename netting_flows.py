import ndjson

all_flow = ndjson.load(open("data/pickhardtpay_prob_flow.ndjson", "r"))
print(f"Total number of flows: {len(all_flow):,}")

print("- selecting only settled flows")
settled_flows = []
for e in all_flow:
    if e[7] == "SETTLED":
        settled_flows.append(e)
print(f"Number of flows after removing non-settled flows: {len(settled_flows):,}")

gross_flow = 0
for e in settled_flows:
    gross_flow += e[5]
print(f"Gross flow amount over all {len(settled_flows):,} settled flows: {gross_flow:,}")
print("-----------------------------------------------------------------------------")
print("- aggregating flows on each edge")
total_number_of_settled_flows = len(settled_flows)
idx = 0

for e in settled_flows:
    idx += 1
    idy = 0
    for f in settled_flows:
        idy += 1
        if e == f:
            continue
        if f[0] == e[0] and f[1] == e[1] and f[2] == e[2]:
            e[5] += f[5]
            settled_flows.remove(f)
        if idy % 500000 == 0:
            print(f"({idx:,} - {idy:,})")
gross_flow = 0
print("     calculating gross flow...")
for e in settled_flows:
    gross_flow += e[5]

print(f"Number of flows/edges after aggregating flow on edge: {len(settled_flows):,} "
      f"({(total_number_of_settled_flows - len(settled_flows)):,} flows collapsed)")

print("-----------------------------------------------------------------------------")
print("- calculating sum of net flow amount, netting bi-directional flows on an edge")
edges_with_flow_on_return_channel = 0
for e in settled_flows:
    for f in settled_flows:
        if e[0] == f[1] and e[1] == f[0] and e[2] == f[2] and e[5] > 0 and f[5] > 0:
            e[5] -= f[5]
            edges_with_flow_on_return_channel += 1
            settled_flows.remove(f)

for e in settled_flows:
    if e[5] < 0:
        receiver = e[1]
        e[1] = e[0]
        e[0] = receiver
        e[5] = -e[5]

print(f"Number of flows after netting: {len(settled_flows):,} "
      f"({edges_with_flow_on_return_channel:,} edges with bi-directional flows.)")
ndjson.dump(settled_flows, open("data/1337_12345_edges_with_netted_flows.ndjson", "w"))

net_flow = 0
for e in settled_flows:
    net_flow += e[5]
print(f"Net flow amount over all edges: {net_flow:,}")
