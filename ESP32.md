# XIAO ESP32-S3 Sense — 비전 어시스턴트 클라이언트 세팅 가이드

**프로젝트 목적:** 시각장애인용 비전 어시스턴트 디바이스 (클라이언트)
카메라 + 마이크 데이터를 WebSocket으로 서버에 전송하고, 서버의 오디오 응답을 받아 스피커로 재생한다.

---

## 1. 시스템 아키텍처

```
┌─────────────────────────────────────────────────────────┐
│             XIAO ESP32-S3 Sense (클라이언트)              │
│                                                          │
│  [OV3660 카메라] ──┐                                     │
│                    ├──► WebSocket TX ──► 서버            │
│  [PDM 마이크]  ────┘                                     │
│                                                          │
│  [DFR0954 스피커] ◄─── WebSocket RX ◄── 서버            │
│                                                          │
│                   WiFi (2.4GHz)                          │
└─────────────────────────────────────────────────────────┘
```

**데이터 흐름**
1. 카메라 → JPEG 캡처 → WebSocket 바이너리 전송
2. 마이크 → PCM 녹음 (16kHz, 16bit, Mono) → WebSocket 바이너리 전송
3. WebSocket 수신 → PCM 오디오 → I2S → DFR0954 → 스피커 출력

---

## 2. 하드웨어 구성

### 2-1. Seeed Studio XIAO ESP32-S3 Sense

| 항목 | 내용 |
|------|------|
| MCU | ESP32-S3, Xtensa LX7 듀얼코어, 최대 240MHz |
| WiFi | IEEE 802.11 b/g/n (2.4GHz, WiFi 4) — **5GHz 미지원** |
| Bluetooth | Bluetooth 5.0 LE |
| Flash | 8MB (QIO) |
| PSRAM | **8MB OPI PSRAM** (Octal SPI, 카메라/오디오 버퍼에 필수) |
| 온보드 카메라 | OV3660, 최대 2048×1536 (3MP) |
| 온보드 마이크 | 디지털 PDM 마이크 (I2S PDM_RX 모드) |
| 외부 스피커 | DFR0954 (MAX98357A) — I2S STD_TX 모드 |
| I2S 페리페럴 | 2개 (I2S0, I2S1) — 마이크·스피커 동시 사용 가능 |

### 2-2. 핀 배정

**내부 고정 핀 (보드 내장, 변경 불가)**

| 기능 | GPIO |
|------|------|
| 카메라 XCLK | GPIO 9 |
| 카메라 PCLK | GPIO 13 |
| 카메라 VSYNC | GPIO 38 |
| 카메라 HREF | GPIO 47 |
| 카메라 SIOD (SDA) | GPIO 40 |
| 카메라 SIOC (SCL) | GPIO 39 |
| 카메라 D0~D7 | GPIO 15, 17, 18, 16, 14, 12, 10, 11 |
| PDM 마이크 CLK | **GPIO 42** |
| PDM 마이크 DATA | **GPIO 41** |

**외부 연결 핀 (사용자 설정)**

| XIAO 핀 | GPIO | 용도 |
|---------|------|------|
| D0 | GPIO 1 | I2S LRC (스피커) |
| D1 | GPIO 2 | I2S BCLK (스피커) |
| D2 | GPIO 3 | I2S DIN (스피커) |
| D3 | GPIO 4 | 버튼 (INPUT_PULLUP) |
| VUSB | — | DFR0954 VCC 5V 공급 |
| GND | — | 공통 GND |

### 2-3. DFRobot DFR0954 (MAX98357A I2S 앰프)

| 항목 | 내용 |
|------|------|
| 핵심 IC | Maxim MAX98357A |
| 앰프 방식 | Class D |
| 전원 | 3.3V ~ 5V (VUSB 5V 권장) |
| 최대 출력 | 2.5W @ 5V, 4Ω 스피커 |
| 인터페이스 | I2S 3선 (BCLK, LRCLK, DIN) |
| 기본 게인 | 9 dB (GAIN 핀 미연결) |

**게인 설정**

| GAIN 핀 연결 | 게인 |
|-------------|------|
| 미연결 (기본) | 9 dB |
| GND에 직결 | 12 dB |
| 100kΩ → GND | 15 dB |

---

## 3. 배선 (Wiring)

```
DFR0954 핀    →   XIAO ESP32-S3
─────────────────────────────────────
VCC          →   VUSB  (5V, USB 연결 필요)
GND          →   GND
LRC          →   D0    (GPIO 1)  ← I2S Word Select
BCLK         →   D1    (GPIO 2)  ← I2S Bit Clock
DIN          →   D2    (GPIO 3)  ← I2S Data In
SPK+ / SPK-  →   스피커 (4Ω ~ 8Ω)

버튼 한쪽     →   D3    (GPIO 4)
버튼 반대쪽   →   GND
```

> **VUSB 주의:** USB 케이블 연결 상태에서만 5V 출력. 배터리 단독 운용 시 3.3V 핀 사용(출력 감소).

---

## 4. I2S 페리페럴 분리 구성

ESP32-S3는 I2S 페리페럴이 2개이므로 마이크와 스피커를 동시에 운용할 수 있다.

| 페리페럴 | 역할 | 모드 | GPIO |
|---------|------|------|------|
| I2S0 | PDM 마이크 입력 | PDM_RX (Mono) | CLK=42, DATA=41 |
| I2S1 | DFR0954 스피커 출력 | STD_TX (Stereo) | BCLK=2, LRC=1, DIN=3 |

**마이크 I2S 설정 (ESP32 Arduino Core 3.x)**
```cpp
#include <ESP_I2S.h>

I2SClass I2S_MIC;

void micBegin() {
  I2S_MIC.setPinsPdmRx(42, 41);           // CLK, DATA
  I2S_MIC.begin(I2S_MODE_PDM_RX,
                16000,                   // 샘플레이트: 16kHz
                I2S_DATA_BIT_WIDTH_16BIT,
                I2S_SLOT_MODE_MONO);
}
```

> PDM 마이크는 **Mono, 16kHz, 16bit** 고정. 다른 샘플레이트는 불안정.

---

## 5. Arduino IDE 보드 세팅

`도구(Tools)` 메뉴 설정:

| 항목 | 설정값 |
|------|--------|
| Board | **Seeed Studio XIAO ESP32S3** |
| Port | 연결된 COM 포트 |
| Upload Speed | 921600 |
| USB Mode | Hardware CDC and JTAG |
| USB CDC On Boot | **Enabled** (Serial 모니터 사용 시) |
| CPU Frequency | **240MHz (WiFi)** |
| Flash Mode | QIO 80MHz |
| Flash Size | **8MB (64Mb)** |
| **PSRAM** | **OPI PSRAM** ← 필수 (카메라·오디오 버퍼) |
| **Partition Scheme** | **Huge APP (3MB No OTA/1MB SPIFFS)** ← 필수 |
| Core Debug Level | None |

### 각 설정이 필수인 이유

| 설정 | 이유 |
|------|------|
| PSRAM: OPI PSRAM | OV3660 카메라 프레임 버퍼 + 오디오 디코더 버퍼 모두 PSRAM 사용. 비활성화 시 카메라 초기화 실패 |
| Partition: Huge APP | esp_camera + WebSocket + I2S 라이브러리 합산 바이너리가 기본 앱 영역(~1.2MB) 초과. 3MB 앱 영역 필요 |

---

## 6. 필수 라이브러리

### 6-1. esp_camera (ESP32 Arduino Core 내장)

카메라 캡처에 사용. 별도 설치 불필요.

```cpp
#include "esp_camera.h"

// XIAO ESP32-S3 Sense 카메라 핀 정의
camera_config_t config;
config.ledc_channel = LEDC_CHANNEL_0;
config.ledc_timer   = LEDC_TIMER_0;
config.pin_d0       = 15;  config.pin_d1 = 17;
config.pin_d2       = 18;  config.pin_d3 = 16;
config.pin_d4       = 14;  config.pin_d5 = 12;
config.pin_d6       = 10;  config.pin_d7 = 11;
config.pin_xclk     = 9;
config.pin_pclk     = 13;
config.pin_vsync    = 38;
config.pin_href     = 47;
config.pin_sscb_sda = 40;
config.pin_sscb_scl = 39;
config.pin_pwdn     = -1;  // 없음
config.pin_reset    = -1;  // 없음
config.xclk_freq_hz = 20000000;
config.pixel_format = PIXFORMAT_JPEG;    // WebSocket 전송용 JPEG
config.frame_size   = FRAMESIZE_QVGA;   // 320×240 (전송 속도 우선)
config.jpeg_quality = 12;               // 품질 (0=최고, 63=최저)
config.fb_count     = 2;               // 더블 버퍼 (PSRAM 필요)
config.fb_location  = CAMERA_FB_IN_PSRAM;
config.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

esp_err_t err = esp_camera_init(&config);
```

**카메라 프레임 캡처**
```cpp
camera_fb_t *fb = esp_camera_fb_get();
// fb->buf  : JPEG 데이터 포인터
// fb->len  : 바이트 수
esp_camera_fb_return(fb);  // 반드시 반환
```

**frame_size 옵션** (전송 대역폭과 처리 속도 고려)

| 옵션 | 해상도 | 용도 |
|------|--------|------|
| FRAMESIZE_QQVGA | 160×120 | 초저지연 |
| FRAMESIZE_QVGA | 320×240 | 권장 (균형) |
| FRAMESIZE_VGA | 640×480 | 고화질 (느림) |

### 6-2. ArduinoWebsockets (by gilmaimon)

- **설치:** 라이브러리 매니저 → `ArduinoWebsockets` 검색
- **GitHub:** https://github.com/gilmaimon/ArduinoWebsockets

```cpp
#include <ArduinoWebsockets.h>
using namespace websockets;

WebsocketsClient wsClient;

void wsConnect() {
  wsClient.onMessage([](WebsocketsMessage msg) {
    if (msg.isBinary()) {
      // 서버에서 받은 PCM 오디오 → I2S로 출력
      i2s_write(I2S_NUM_1, msg.c_str(), msg.length(), &written, portMAX_DELAY);
    }
  });
  wsClient.connect("ws://서버IP:포트/경로");
}

// 카메라 프레임 전송
wsClient.sendBinary((const char*)fb->buf, fb->len);

// 마이크 오디오 전송
wsClient.sendBinary((const char*)micBuf, micBufLen);

// loop()에서 호출
wsClient.poll();
```

### 6-3. ESP32-audioI2S (by schreibfaul1) — 선택 사항

서버에서 수신한 오디오가 MP3/AAC 인코딩된 경우에만 필요. 서버가 **PCM raw** 오디오를 전송한다면 직접 I2S write로 충분하며 이 라이브러리는 불필요.

- **GitHub:** https://github.com/schreibfaul1/ESP32-audioI2S
- **요구사항:** 멀티코어 필수, PSRAM 최소 2MB

---

## 7. 전체 루프 흐름

```
setup()
  └─ WiFi 연결
  └─ 카메라 초기화 (esp_camera_init)
  └─ 마이크 I2S 초기화 (I2S0, PDM_RX)
  └─ 스피커 I2S 초기화 (I2S1, STD_TX)
  └─ WebSocket 연결 + onMessage 콜백 등록

loop()
  ├─ wsClient.poll()              ← WebSocket 수신 처리 (콜백 트리거)
  ├─ 카메라 프레임 캡처 → sendBinary
  ├─ 마이크 샘플 읽기  → sendBinary
  └─ 버튼 입력 처리
```

> `wsClient.poll()`은 loop()에서 매 틱 호출해야 수신 지연 없이 오디오를 재생할 수 있다.

---

## 8. 메모리 참고

| 자원 | 용도 | 위치 |
|------|------|------|
| PSRAM 8MB | 카메라 프레임 버퍼 (더블 버퍼) | fb_location = PSRAM |
| PSRAM | WebSocket 수신 버퍼 | 라이브러리 내부 |
| SRAM ~512KB | 스택, 전역 변수, FreeRTOS | 내부 SRAM |
| Flash 3MB (앱) | 펌웨어 바이너리 | Huge APP 파티션 |

---

## 9. 트러블슈팅

| 증상 | 원인 및 해결 |
|------|------------|
| 카메라 초기화 실패 (`ESP_FAIL`) | PSRAM 비활성화 → Tools > PSRAM > OPI PSRAM |
| 플래시 업로드 크기 초과 | Partition Scheme → Huge APP 으로 변경 |
| 소리 없음 (스피커) | VUSB 5V 공급 확인, I2S 핀 배선 재확인 |
| 마이크 무반응 | Sense 확장 보드 장착 여부 확인 (GPIO 41/42는 확장 보드에 연결됨) |
| WebSocket 연결 끊김 | WiFi 2.4GHz 대역 확인, `wsClient.poll()` 호출 주기 확인 |
| WiFi 연결 실패 | 2.4GHz AP 필요 (5GHz 미지원), SSID/PW 확인 |
| 카메라+마이크 동시 I2S 충돌 | I2S0(마이크)과 I2S1(스피커)을 분리해서 사용하고 있는지 확인 |
| JPEG 품질 낮음 | `jpeg_quality` 값 낮추기 (숫자 낮을수록 고품질, 파일 크기 증가) |

---

## 10. 참고 자료

- [Seeed Wiki - XIAO ESP32-S3 Getting Started](https://wiki.seeedstudio.com/xiao_esp32s3_getting_started/)
- [Seeed Wiki - Camera Usage](https://wiki.seeedstudio.com/xiao_esp32s3_camera_usage/)
- [Seeed Wiki - Microphone Usage](https://wiki.seeedstudio.com/xiao_esp32s3_sense_mic/)
- [Seeed Wiki - XIAO ESP32-S3 Pin Multiplexing](https://wiki.seeedstudio.com/xiao_esp32s3_pin_multiplexing/)
- [DFRobot DFR0954 Wiki (MAX98357A)](https://wiki.dfrobot.com/SKU_DFR0954_MAX98357_I2S_Amplifier_Module)
- [ArduinoWebsockets GitHub](https://github.com/gilmaimon/ArduinoWebsockets)
- [ESP32-audioI2S GitHub](https://github.com/schreibfaul1/ESP32-audioI2S)
- [Hackster - Miniature Voice Assistant on XIAO ESP32S3](https://www.hackster.io/kong5/miniature-voice-assistant-base-on-xiao-esp32s3-sense-5ed97a)
