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
        const actions = status.actions || [{channel:'head',label:status.head_action},{channel:'arms',label:status.arm_action}];
        for (const item of actions) {
            if (item.label && item.label !== 'unknown') this.events.set(item.channel,{text:VisionPanel.labels[item.label] || item.label,time:this.received});
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
            for (const id of ['cv-identity','cv-emotion','cv-action','cv-joints','cv-cues','cv-head','cv-arms','cv-left-hand','cv-right-hand','cv-gaze','cv-eyes','cv-blinks','cv-distance','cv-objects']) this.text(id,'Chưa rõ');
            this.meters({});
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
        const emotionLabel = VisionPanel.labels[emotion] || 'Chưa rõ';
        this.stable('cv-emotion',emotionLabel,emotion === 'unknown',150);
        const emotionElement = this.document.getElementById('cv-emotion');
        const shownEmotion = this.fields.get('cv-emotion')?.shown || 'Chưa rõ';
        const hasCurrentScore = emotion !== 'unknown' && shownEmotion === emotionLabel && Number.isFinite(s.emotion_confidence);
        const fallbackEmotion = hasCurrentScore ? `${shownEmotion} (${Math.round(s.emotion_confidence*100)}%)` : shownEmotion;
        const ranking = offline ? '' : this.emotionRanking(s.emotion_probs || {});
        this.text('cv-emotion',ranking || fallbackEmotion);
        if (emotionElement) emotionElement.title = ranking
            ? 'Tối đa 5 đầu ra FER+ có điểm cao nhất, xếp theo thứ tự giảm dần.'
            : `Nguồn: ${s.emotion_source || 'unknown'} · độ tin cậy ${Math.round((s.emotion_confidence || 0)*100)}% (ước lượng từ mô hình/tín hiệu mặt)`;
        if (offline) this.events.clear();
        const active = [...this.events.values()].filter(event=>this.now()-event.time<1800);
        this.text('cv-action',active.length ? active.map(event=>event.text).join(' · ') : 'Chưa rõ');
        for (const [channel,id] of [['head','cv-head'],['arms','cv-arms'],['left_hand','cv-left-hand'],['right_hand','cv-right-hand']]) {
            const event = this.events.get(channel);
            this.text(id,event && this.now()-event.time<1800 ? event.text : 'Chưa rõ');
        }
        const count = offline ? 0 : Object.values(s.upper_body_joints || {}).filter(j=>j.visible).length;
        this.stable('cv-joints',`${count}/6 khớp`,count === 0,750);
        const cues = s.expression_cues || {};
        const cue = offline ? 'Chưa rõ' : cues.smile > .3 ? 'Khóe miệng cười' : cues.brow_down > .3 ? 'Nhíu chân mày'
            : cues.brow_inner_up > .25 ? 'Nâng đầu chân mày' : cues.mouth_frown > .12 ? 'Hạ khóe miệng' : 'Chưa rõ';
        this.stable('cv-cues',cue,cue === 'Chưa rõ',750);
        const eyes = offline ? {} : s.eyes || {};
        this.stable('cv-gaze',({toward_camera:'Có vẻ nhìn camera',away:'Nhìn hướng khác'})[eyes.gaze] || 'Chưa rõ',!eyes.gaze || eyes.gaze==='unknown',300);
        this.stable('cv-eyes',({open:'Mắt mở',closed:'Mắt nhắm',prolonged_closure:'Nhắm mắt kéo dài'})[eyes.state] || 'Chưa rõ',!eyes.state || eyes.state==='unknown',250);
        this.text('cv-blinks',eyes.blink_rate_per_min == null ? 'Đang lấy mẫu' : `~${Math.round(eyes.blink_rate_per_min)}/phút (ước lượng)`);
        const distance = offline ? {} : s.distance || {};
        this.text('cv-distance',distance.cm == null ? 'Chưa rõ' : `~${Math.round(distance.cm/5)*5} cm${distance.source==='assumed_fov'?' *':''}`);
        const objects = offline ? [] : s.objects || [];
        const names = [...new Set(objects.map(o=>(VisionPanel.objects[o.label] || o.label)+(o.near_hands?.length?' (gần tay)':'')))];
        this.stable('cv-objects',names.join(', ') || 'Chưa thấy',!names.length,500);
        this.meters(offline ? {} : s.emotion_probs || {},offline ? {} : s.expression_intensities || {});
    }
    emotionRanking(probs) {
        return VisionPanel.emotions
            .map((name,index)=>({name,index,value:Number(probs[name])}))
            .filter(item=>Number.isFinite(item.value) && item.value >= .005)
            .sort((a,b)=>b.value-a.value || a.index-b.index)
            .slice(0,5)
            .map(item=>`${VisionPanel.labels[item.name]} (${Math.round(Math.max(0,Math.min(1,item.value))*100)}%)`)
            .join(', ');
    }
    meters(probs, intensities = {}) {
        for (const name of VisionPanel.emotions) {
            const value = Math.max(0,Math.min(1,probs[name] || 0));
            const meter = this.document.getElementById(`cv-prob-${name}`);
            if (meter) meter.value = value;
            this.text(`cv-score-${name}`,probs[name] == null ? '—' : `${Math.round(value*100)}%`);
        }
        for (const name of ['happy','surprised','sad','angry','disgust','fear','contempt']) {
            const value = Math.max(0,Math.min(1,intensities[name] || 0));
            const meter = this.document.getElementById(`cv-intensity-${name}`);
            if (meter) meter.value = value;
            this.text(`cv-intensity-score-${name}`,intensities[name] == null ? '—' : `${Math.round(value*100)}%`);
        }
    }
}
VisionPanel.emotions = ['neutral','happy','surprised','sad','angry','disgust','fear','contempt'];
VisionPanel.labels = {unknown:'Chưa rõ',neutral:'Trung tính',happy:'Vui',sad:'Buồn',angry:'Giận',
    surprised:'Ngạc nhiên',disgust:'Chán ghét',fear:'Sợ',contempt:'Khinh miệt',waving:'Vẫy tay chào',
    hand_raised:'Giơ một tay',both_hands_up:'Giơ hai tay',head_nod:'Gật đầu',head_shake:'Lắc đầu',
    victory:'Hai ngón V / hello',thumbs_up:'Ngón cái / like',open_palm:'Xòe bàn tay',pointing:'Chỉ một ngón',fist:'Nắm tay'};
VisionPanel.objects = {'cup':'Ly/cốc','bottle':'Chai','book':'Sách','cell phone':'Điện thoại','laptop':'Laptop','remote':'Điều khiển'};
if (typeof module !== 'undefined') module.exports = {VisionPanel};
