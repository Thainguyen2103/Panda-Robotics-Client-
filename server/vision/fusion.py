"""Combine independent vision channels without overwriting their meaning."""


def combined_actions(head,arm,hands):
    items = [dict(channel="head",label=head)] if head != "unknown" else []
    if arm != "unknown": items.append(dict(channel="arms",label=arm))
    for hand in hands:
        if hand["gesture"] != "unknown":
            items.append(dict(channel=hand["side"]+"_hand",label=hand["gesture"],
                              associated=bool(hand.get("associated"))))
    return items


def nearby_objects(objects,hands):
    output = []
    for obj in objects:
        x,y,w,h = obj["box"]
        sides = []
        for hand in hands:
            if not hand["associated"]: continue
            for px,py,_ in hand["landmarks"]:
                if x-.03 <= px <= x+w+.03 and y-.03 <= py <= y+h+.03:
                    sides.append(hand["side"])
                    break
        output.append({**obj,"near_hands":sorted(set(sides))})
    return output
