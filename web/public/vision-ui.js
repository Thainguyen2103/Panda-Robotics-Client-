/* Presentation smoothing only. Robot decisions still use fresh backend results. */
class VisionPanel {
    constructor(document, now = () => Date.now()) {
        this.document = document;
        this.now = now;
        this.status = null;
        this.received = 0;
        this.fields = new Map();
        this.events = new Map();
    }
    receive(status) {
        this.status = status;
        this.received = this.now();
        // Preserve brief events even when several messages arrive between UI ticks.
        for (const key of ['head_action','arm_action']) {
            const label = status[key];
            if (label && label !== 'unknown') this.events.set(key,{text:VisionPanel.labels[label] || label,time:this.received});
        }
    }
    text(id, value) {
        const element = this.document.getElementById(id);
        if (element && element.textContent !== value) element.textContent = value;
    }
    stable(id, candidate, unknown = false, delay = 500) {
        const now = this.now();
        let field = this.fields.get(id);
        if (!field) {
            field = {candidate, since: now, shown: 'Chưa rõ'};
            this.fields.set(id, field);
        }
        if (candidate !== field.candidate) {
            field.candidate = candidate;
            field.since = now;
        }
        if (now - field.since >= (unknown ? 1500 : delay)) field.shown = candidate;
        this.text(id, field.shown);
    }
    tick() {
        if (!this.status) return;
        const s = this.status;
        const stale = this.now() - this.received > 4000;
        const offline = stale || ['camera_unavailable', 'inference_stale'].includes(s.status);
        if (stale) {
            this.fields.clear();
            this.events.clear();
            this.text('cv-health', 'Mất kết nối Vision');
            for (const id of ['cv-identity','cv-emotion','cv-action','cv-joints','cv-cues']) this.text(id,'Chưa rõ');
            return;
        }
        const states = {ok:'Đang chạy',degraded:'Thiếu / lỗi mô hình',camera_unavailable:'Mất camera',inference_stale:'AI phản hồi chậm',starting:'Đang khởi động'};
        this.stable('cv-health',states[s.status] || 'Đang chờ',false,750);
        const health = this.document.getElementById('cv-health');
        if (health) health.title = `${s.inference_ms || 0} ms · ${Object.keys(s.errors || {}).join(', ')}`;
        const identity = offline ? 'Chưa rõ' : !s.person_detected ? 'Không thấy người'
            : !s.enrolled ? 'Chưa đăng ký' : s.identity === 'Master' ? 'Chủ nhân'
            : s.identity === 'Guest' ? 'Khách' : 'Chưa rõ';
        this.stable('cv-identity',identity,identity === 'Chưa rõ' || !s.person_detected);
        const emotion = offline ? 'unknown' : s.emotion;
        this.stable('cv-emotion',VisionPanel.labels[emotion] || 'Chưa rõ',emotion === 'unknown');
        const emotionElement = this.document.getElementById('cv-emotion');
        if (emotionElement) emotionElement.title = `Điểm FER hiện tại: ${Math.round((s.emotion_confidence || 0)*100)}%`;
        if (offline) this.events.clear();
        const active = [...this.events.values()].filter(event=>this.now()-event.time<1800);
        this.text('cv-action',active.length ? active.map(event=>event.text).join(' · ') : 'Chưa rõ');
        const count = offline ? 0 : Object.values(s.upper_body_joints || {}).filter(j=>j.visible).length;
        this.stable('cv-joints',`${count}/6 khớp`,count === 0,750);
        const cues = s.expression_cues || {};
        const cue = offline ? 'Chưa rõ' : cues.brow_down > .3 ? 'Nhíu chân mày'
            : cues.brow_inner_up > .25 ? 'Nâng đầu chân mày' : cues.mouth_frown > .12 ? 'Hạ khóe miệng' : 'Chưa rõ';
        this.stable('cv-cues',cue,cue === 'Chưa rõ',750);
    }
}
VisionPanel.labels = {unknown:'Chưa rõ',neutral:'Trung tính',happy:'Vui',sad:'Buồn',angry:'Giận',
    surprised:'Ngạc nhiên',disgust:'Chán ghét',fear:'Sợ',contempt:'Khinh miệt',waving:'Vẫy tay chào',
    hand_raised:'Giơ một tay',both_hands_up:'Giơ hai tay',head_nod:'Gật đầu',head_shake:'Lắc đầu'};
if (typeof module !== 'undefined') module.exports = {VisionPanel};
