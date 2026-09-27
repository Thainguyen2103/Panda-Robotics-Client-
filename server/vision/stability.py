"""Small temporal stabilizers shared by independent vision channels."""


class StableLabel:
    def __init__(self, count=3, hold=0):
        self.count = count
        self.hold = hold
        self.reset()

    def reset(self):
        self.pending, self.samples = "unknown", 0
        self.value, self.uncertain = "unknown", 0

    def update(self, label):
        if label == "unknown":
            self.pending,self.samples = "unknown",0
            self.uncertain += 1
            if self.uncertain > self.hold:
                self.value = "unknown"
            return self.value
        self.samples = self.samples+1 if label == self.pending else 1
        self.pending = label
        if self.samples >= self.count:
            self.value,self.uncertain = label,0
        else:
            self.uncertain += 1
            if self.uncertain > self.hold:
                self.value = "unknown"
        return self.value
