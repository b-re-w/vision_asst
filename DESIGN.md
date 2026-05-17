# Vision Assistant — Web Client Design Spec

## Aesthetic Direction
**"Deep Void"** — 몽환적이고 공허한 우주 느낌. 유저가 말하는 동안 떠있는 것 같은 감각.

## Color Palette
| 역할 | 값 |
|------|-----|
| Background | `#080c14` (deep space) |
| Surface | `rgba(255,255,255,0.03)` (frosted void) |
| Border | `rgba(255,255,255,0.06)` |
| Accent Purple | `#8b7cf8` (user / active) |
| Accent Cyan | `#4ecdc4` (model / connected) |
| Danger | `#ff4757` (rec indicator) |
| Text | `rgba(255,255,255,0.82)` |
| Text Muted | `rgba(255,255,255,0.35)` |

## Layout
```
┌──────────────── Container (460×820, centered) ─────────────────┐
│  ✦  VISION ASSISTANT                               ●           │  ← header
│  ┌──────────────────────────────────────────────────────────┐  │
│  │                  Camera Feed (4:3)                       │  │  ← camera
│  │                                         ● rec            │  │
│  └──────────────────────────────────────────────────────────┘  │
│  ┌──────────────────────────────────────────────────────────┐  │
│  │ ← blur fade at top                                        │  │  ← chat
│  │  [U]  ▇▃▅▇▄▂▅▃▇▄▂▅  (user waveform)                   │  │
│  │       "사용자 전사 텍스트 (ASR 없이 생략 가능)"           │  │
│  │             ▇▃▅▇▄▂▅▃▇▄▂▅  [✦]  (model waveform)        │  │
│  │             "Gemini 응답 텍스트"                          │  │
│  └──────────────────────────────────────────────────────────┘  │
│  [ Connect / Disconnect ]               [mic-bars]             │  ← controls
└────────────────────────────────────────────────────────────────┘
```

## Visual Effects
- **Container**: `backdrop-filter: blur(40px)`, `box-shadow: 0 0 80px rgba(100,80,200,0.08)`
- **Camera border**: soft purple glow `box-shadow: 0 0 40px rgba(139,124,248,0.15)`
- **Chat fade-top**: `mask-image: linear-gradient(to bottom, transparent 0%, black 18%)`
- **Message scroll-out**: JS scroll listener → `opacity` + `filter: blur()` on top messages
- **Waveform bars**: CSS `@keyframes bar-wave` scaleY, different `animation-delay` per bar
- **Active mic**: teal glow ring, bar animation driven by Web Audio AnalyserNode
- **Logo ✦**: `drop-shadow` pulse `@keyframes` glow

## Component States
| Component | Default | Active | Ended |
|-----------|---------|--------|-------|
| User bubble | — | purple bars animated | bars static (frozen amplitude) |
| Model bubble | — | cyan bars animated | bars static + text visible |
| Mic indicator | dim circle | teal ring + animated bars | dim |
| Rec dot | hidden | red blinking | hidden |
| Status dot | grey | teal glowing | grey |

## Typography
- Family: `-apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif`
- Header: 13px, weight 300, letter-spacing 0.15em, uppercase
- Transcript: 13px, weight 300, line-height 1.55, letter-spacing 0.02em
- All text: `rgba(255,255,255,0.82)` base, muted for labels
