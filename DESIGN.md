# Vision Assistant — Web Client Design Spec

## Aesthetic Direction
**"Living Window"** — 카메라 피드가 배경 전체로 확장되어, UI가 현실 위에 떠있는 느낌.  
유저의 시선이 자연스럽게 카메라 피드와 대화 내용 사이를 오가도록 설계.

---

## Background Layer System

```
z-index 0  │  #bg-video       : 카메라 피드 (전체화면, blur+dim)
z-index 1  │  .scene          : 반투명 vignette overlay
z-index 2  │  .container      : 글래스모피즘 메인 카드
```

### Background Camera Feed (`#bg-video`)
- `position: fixed; inset: 0; width: 100%; height: 100%; object-fit: cover`
- `transform: scale(1.08)` — blur 처리 시 발생하는 엣지 노출 방지
- `filter: blur(28px) brightness(0.22) saturate(1.6)` — 배경은 어둡고 몽환적으로
- 동일한 `MediaStream`을 패널 내 `#video`와 공유 (`bgVideo.srcObject = state.videoStream`)

### Scene Overlay (`.scene`)
- `background: radial-gradient(ellipse 80% 80% at 50% 50%, transparent 30%, rgba(4,6,10,0.55) 100%)`
- 카드 바깥 가장자리를 더 어둡게 만들어 카드가 부각되도록 함

---

## Color Palette
| 역할 | 값 |
|------|-----|
| Background (body fallback) | `#080c14` (deep space) |
| Container glass | `rgba(8,12,20,0.45)` + `backdrop-filter: blur(40px) saturate(180%)` |
| Border | `rgba(255,255,255,0.08)` |
| Accent Purple | `#8b7cf8` (user / active) |
| Accent Cyan | `#4ecdc4` (model / connected) |
| Danger | `#ff4757` (rec indicator) |
| Text | `rgba(255,255,255,0.82)` |
| Text Muted | `rgba(255,255,255,0.35)` |

---

## Layout
```
┌──────────── #bg-video (전체화면, blur+dim 카메라) ──────────────┐
│  ┌────────── .scene (vignette overlay) ───────────────────────┐  │
│  │  ┌──── .container (560px max, glassmorphism card) ───────┐ │  │
│  │  │  ✦  VISION ASSISTANT                          ●       │ │  │
│  │  │  ┌──────────────── Camera (4:3) ─────────────────┐   │ │  │
│  │  │  │       [선명한 카메라 프리뷰]           ● rec   │   │ │  │
│  │  │  └───────────────────────────────────────────────┘   │ │  │
│  │  │  ← blur fade at top                                   │ │  │
│  │  │  [U]  ▇▃▅▇▄▂▅▃▇▄▂▅  user waveform + transcript      │ │  │
│  │  │            ▇▃▅▇▄▂▅▃▇▄▂▅  [✦]  model waveform        │ │  │
│  │  │            "Gemini 응답 텍스트 (char-reveal)"         │ │  │
│  │  │  [ Disconnect ]                        [mic-bars]    │ │  │
│  │  └───────────────────────────────────────────────────────┘ │  │
│  └─────────────────────────────────────────────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
```

---

## Typography
- Family: `'SUITE'` (Variable, CDN) → fallback `-apple-system, sans-serif`
- Header h1: 12px, weight 300, letter-spacing 0.18em, uppercase
- Transcript: 13px, weight 300, line-height 1.55, letter-spacing 0.025em
- Button: 12px, weight 400, letter-spacing 0.06em

---

## Visual Effects
| 요소 | 효과 |
|------|------|
| Background video | `blur(28px) brightness(0.22) saturate(1.6)`, scale 1.08 |
| Container | `backdrop-filter: blur(40px) saturate(180%)`, dark glass tint |
| Logo ✦ | `drop-shadow` pulse `@keyframes glow-pulse` |
| Camera border | Purple glow `rgba(139,124,248,0.22)` |
| Chat fade-top | `mask-image: linear-gradient(to bottom, transparent 0%, black 22%)` |
| Char reveal | blur+brightness flash → overshoot → settle (`char-in` 0.55s spring) |
| Message enter | `translateY(10px) → 0`, opacity 0→1, 0.32s |
| Scroll-out blur | JS scroll listener → top messages fade+blur |

---

## Component States
| Component | Default | Active | Ended |
|-----------|---------|--------|-------|
| User bubble | — | purple bars animated | bars static |
| Model bubble | — | cyan bars animated | bars static + char-reveal text |
| Mic indicator | dim circle | teal ring + bars | dim |
| Rec dot | hidden | red blinking | hidden |
| Status dot | grey | teal glowing | grey |
| bg-video | `#080c14` fallback | live blurred camera | cleared |

---

## Connection Behavior
- **Page load**: 자동 WebSocket 연결 (`DOMContentLoaded`)
- **Server disconnect**: 3초 후 자동 재연결
- **Manual disconnect**: 버튼으로만, 재연결 안 함 (`manualDisconnect` flag)
- **Voice**: Aoede (여성, Gemini `speech_config` 고정)
