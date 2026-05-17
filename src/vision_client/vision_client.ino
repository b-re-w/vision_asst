/*
 * ============================================
 *  XIAO ESP32-S3 Sense — 비전 어시스턴트 클라이언트
 *  Vision Assistant Device for Visually Impaired
 * ============================================
 *
 *  하드웨어:
 *    온보드 OV3660 카메라
 *    온보드 PDM 마이크 (GPIO 42=CLK, GPIO 41=DATA)
 *    DFR0954 스피커  (GPIO 1=LRC, GPIO 2=BCLK, GPIO 3=DIN)
 *    버튼             D3 (GPIO 4) ↔ GND
 *
 *  필수 라이브러리:
 *    ArduinoWebsockets by gilmaimon
 *
 *  Arduino IDE 보드 세팅:
 *    Board:     Seeed Studio XIAO ESP32S3
 *    PSRAM:     OPI PSRAM
 *    Partition: Huge APP (3MB No OTA/1MB SPIFFS)
 *
 *  WebSocket 바이너리 프로토콜:
 *    ESP32 → 서버: [0x01][PCM 16kHz 16bit Mono]
 *    ESP32 → 서버: [0x02][JPEG bytes]
 *    서버 → ESP32: [0x01][PCM 24kHz 16bit Mono]
 */

#include <Arduino.h>
#include <WiFi.h>
#include <ArduinoWebsockets.h>
#include "esp_camera.h"
#include <ESP_I2S.h>

using namespace websockets;

// ─────────────────────────────────────
// 사용자 설정 (수정 필요)
// ─────────────────────────────────────
#define WIFI_SSID      "your-ssid"
#define WIFI_PASSWORD  "your-password"
#define WS_SERVER_URL  "ws://192.168.1.100:8000/ws"

// ─────────────────────────────────────
// 핀 정의
// ─────────────────────────────────────
#define PIN_SPK_BCLK   2
#define PIN_SPK_LRC    1
#define PIN_SPK_DIN    3
#define PIN_MIC_CLK    42
#define PIN_MIC_DATA   41
#define PIN_BUTTON     4

// 카메라 핀 (XIAO ESP32-S3 Sense 고정)
#define CAM_PIN_PWDN   -1
#define CAM_PIN_RESET  -1
#define CAM_PIN_XCLK   9
#define CAM_PIN_SIOD   40
#define CAM_PIN_SIOC   39
#define CAM_PIN_D7     11
#define CAM_PIN_D6     10
#define CAM_PIN_D5     12
#define CAM_PIN_D4     14
#define CAM_PIN_D3     16
#define CAM_PIN_D2     18
#define CAM_PIN_D1     17
#define CAM_PIN_D0     15
#define CAM_PIN_VSYNC  38
#define CAM_PIN_HREF   47
#define CAM_PIN_PCLK   13

// ─────────────────────────────────────
// 오디오 / 카메라 설정
// ─────────────────────────────────────
#define MIC_SAMPLE_RATE   16000
#define SPK_SAMPLE_RATE   24000
#define MIC_CHUNK_MS      20
#define MIC_CHUNK_BYTES   (MIC_SAMPLE_RATE / 1000 * MIC_CHUNK_MS * 2)  // 640

#define CAM_INTERVAL_MS   200   // 5fps

// ─────────────────────────────────────
// 프로토콜 타입 바이트
// ─────────────────────────────────────
#define MSG_AUDIO  0x01
#define MSG_VIDEO  0x02

// ─────────────────────────────────────
// 기타
// ─────────────────────────────────────
#define DEBOUNCE_MS  500

// ─────────────────────────────────────
// 전역 변수
// ─────────────────────────────────────
WebsocketsClient wsClient;
I2SClass         I2S_MIC;
I2SClass         I2S_SPK;

bool             wsConnected   = false;
bool             sessionActive = false;
unsigned long    lastCamTime   = 0;
unsigned long    lastPressTime = 0;

// 마이크 전송 버퍼: [타입 헤더 1바이트] + [PCM]
uint8_t micSendBuf[1 + MIC_CHUNK_BYTES];

// ============================================
// 카메라 초기화
// ============================================
bool initCamera() {
  camera_config_t cfg = {};
  cfg.ledc_channel  = LEDC_CHANNEL_0;
  cfg.ledc_timer    = LEDC_TIMER_0;
  cfg.pin_d0 = CAM_PIN_D0; cfg.pin_d1 = CAM_PIN_D1;
  cfg.pin_d2 = CAM_PIN_D2; cfg.pin_d3 = CAM_PIN_D3;
  cfg.pin_d4 = CAM_PIN_D4; cfg.pin_d5 = CAM_PIN_D5;
  cfg.pin_d6 = CAM_PIN_D6; cfg.pin_d7 = CAM_PIN_D7;
  cfg.pin_xclk     = CAM_PIN_XCLK;
  cfg.pin_pclk     = CAM_PIN_PCLK;
  cfg.pin_vsync    = CAM_PIN_VSYNC;
  cfg.pin_href     = CAM_PIN_HREF;
  cfg.pin_sscb_sda = CAM_PIN_SIOD;
  cfg.pin_sscb_scl = CAM_PIN_SIOC;
  cfg.pin_pwdn     = CAM_PIN_PWDN;
  cfg.pin_reset    = CAM_PIN_RESET;
  cfg.xclk_freq_hz = 20000000;
  cfg.pixel_format = PIXFORMAT_JPEG;
  cfg.frame_size   = FRAMESIZE_QVGA;   // 320×240
  cfg.jpeg_quality = 15;               // 0=최고, 63=최저
  cfg.fb_count     = 2;
  cfg.fb_location  = CAMERA_FB_IN_PSRAM;
  cfg.grab_mode    = CAMERA_GRAB_WHEN_EMPTY;

  if (esp_camera_init(&cfg) != ESP_OK) {
    Serial.println("[CAM] 초기화 실패");
    return false;
  }
  Serial.println("[CAM] 초기화 완료 (OV3660, QVGA, JPEG)");
  return true;
}

// ============================================
// 마이크 초기화 (I2S_NUM_0, PDM_RX, 16kHz)
// ============================================
bool initMicrophone() {
  I2S_MIC.setPinsPdmRx(PIN_MIC_CLK, PIN_MIC_DATA);
  if (!I2S_MIC.begin(I2S_MODE_PDM_RX, MIC_SAMPLE_RATE,
                     I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_MONO)) {
    Serial.println("[MIC] 초기화 실패");
    return false;
  }
  Serial.printf("[MIC] 초기화 완료 (%dHz, 16bit, Mono)\n", MIC_SAMPLE_RATE);
  return true;
}

// ============================================
// 스피커 초기화 (I2S_NUM_1, STD_TX, 24kHz)
// MAX98357A는 혼합 모드(SD 미연결)이므로
// STEREO로 설정하고 L=R=mono_sample 로 전송
// ============================================
bool initSpeaker() {
  I2S_SPK.setPins(PIN_SPK_BCLK, PIN_SPK_LRC, PIN_SPK_DIN);
  if (!I2S_SPK.begin(I2S_MODE_STD, SPK_SAMPLE_RATE,
                     I2S_DATA_BIT_WIDTH_16BIT, I2S_SLOT_MODE_STEREO)) {
    Serial.println("[SPK] 초기화 실패");
    return false;
  }
  Serial.printf("[SPK] 초기화 완료 (%dHz, 16bit, Stereo→Mono)\n", SPK_SAMPLE_RATE);
  return true;
}

// ============================================
// WiFi 연결
// ============================================
void connectWiFi() {
  Serial.printf("[WiFi] 연결 중 [%s]", WIFI_SSID);
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 40) {
    delay(500);
    Serial.print(".");
    retry++;
  }
  if (WiFi.status() == WL_CONNECTED) {
    Serial.printf("\n[WiFi] 연결됨 | IP: %s | RSSI: %d dBm\n",
                  WiFi.localIP().toString().c_str(), WiFi.RSSI());
  } else {
    Serial.println("\n[WiFi] 연결 실패 → 재시작");
    ESP.restart();
  }
}

// ============================================
// WebSocket 연결
// ============================================
void connectWebSocket() {
  // ── 수신 콜백 ────────────────────────────
  wsClient.onMessage([](WebsocketsMessage msg) {
    if (!msg.isBinary() || msg.length() < 2) return;

    const uint8_t* data       = (const uint8_t*)msg.c_str();
    const uint8_t* payload    = data + 1;
    size_t         payloadLen = msg.length() - 1;

    if (data[0] != MSG_AUDIO || payloadLen < 2) return;

    // Gemini 출력: PCM 24kHz 16bit Mono (little-endian)
    // MAX98357A 혼합 모드 대응: 각 mono 샘플을 L/R 양쪽에 복사
    const int16_t* mono   = (const int16_t*)payload;
    size_t         count  = payloadLen / 2;
    int16_t*       stereo = (int16_t*)ps_malloc(count * 4);
    if (!stereo) return;

    for (size_t i = 0; i < count; i++) {
      stereo[i * 2]     = mono[i];
      stereo[i * 2 + 1] = mono[i];
    }
    I2S_SPK.write((const uint8_t*)stereo, count * 4);
    free(stereo);
  });

  // ── 이벤트 콜백 ──────────────────────────
  wsClient.onEvent([](WebsocketsEvent evt, String) {
    switch (evt) {
      case WebsocketsEvent::ConnectionOpened:
        wsConnected = true;
        Serial.println("[WS] 연결됨");
        break;
      case WebsocketsEvent::ConnectionClosed:
        wsConnected   = false;
        sessionActive = false;
        Serial.println("[WS] 연결 끊김");
        break;
      case WebsocketsEvent::GotPing:
        wsClient.pong();
        break;
    }
  });

  Serial.printf("[WS] 연결 중 [%s]\n", WS_SERVER_URL);
  wsClient.connect(WS_SERVER_URL);
}

// ============================================
// 마이크 청크 읽어서 WebSocket 전송
// I2S_MIC.readBytes() 는 MIC_CHUNK_MS(~20ms) 동안 블로킹
// ============================================
void sendMicChunk() {
  micSendBuf[0] = MSG_AUDIO;
  size_t bytes = I2S_MIC.readBytes((char*)(micSendBuf + 1), MIC_CHUNK_BYTES);
  if (bytes > 0) {
    wsClient.sendBinary((const char*)micSendBuf, 1 + bytes);
  }
}

// ============================================
// 카메라 프레임 캡처 후 WebSocket 전송
// ============================================
void sendCameraFrame() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    Serial.println("[CAM] 캡처 실패");
    return;
  }

  uint8_t* buf = (uint8_t*)ps_malloc(1 + fb->len);
  if (buf) {
    buf[0] = MSG_VIDEO;
    memcpy(buf + 1, fb->buf, fb->len);
    wsClient.sendBinary((const char*)buf, 1 + fb->len);
    free(buf);
  }
  esp_camera_fb_return(fb);
}

// ============================================
// 버튼 처리 — 누를 때마다 세션 시작/중지 토글
// ============================================
void handleButton() {
  if (digitalRead(PIN_BUTTON) != LOW) return;
  unsigned long now = millis();
  if (now - lastPressTime < DEBOUNCE_MS) return;
  lastPressTime = now;

  sessionActive = !sessionActive;
  Serial.println(sessionActive ? "[BTN] 세션 시작 ▶" : "[BTN] 세션 중지 ■");
}

// ============================================
// setup
// ============================================
void setup() {
  Serial.begin(115200);
  delay(500);

  Serial.println("\n================================");
  Serial.println("  비전 어시스턴트 클라이언트");
  Serial.println("================================");

  pinMode(PIN_BUTTON, INPUT_PULLUP);

  if (!initCamera())     { Serial.println("HALT: 카메라"); while (1) delay(1000); }
  if (!initMicrophone()) { Serial.println("HALT: 마이크"); while (1) delay(1000); }
  if (!initSpeaker())    { Serial.println("HALT: 스피커"); while (1) delay(1000); }

  connectWiFi();
  connectWebSocket();

  Serial.println("\n[준비 완료] 버튼을 눌러 세션을 시작하세요.");
}

// ============================================
// loop
// ============================================
void loop() {
  // 1. WebSocket 수신 처리 (오디오 콜백 트리거)
  if (wsConnected) wsClient.poll();

  // 2. 버튼
  handleButton();

  // 3. 세션 활성 중 데이터 전송
  if (sessionActive && wsConnected) {
    // 마이크: ~20ms 블로킹 read → 즉시 전송
    sendMicChunk();

    // 카메라: 200ms 간격 (5fps)
    unsigned long now = millis();
    if (now - lastCamTime >= CAM_INTERVAL_MS) {
      lastCamTime = now;
      sendCameraFrame();
    }
  }

  // 4. 재연결
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("[WiFi] 끊김 → 재연결");
    connectWiFi();
  } else if (!wsConnected) {
    Serial.println("[WS] 재연결 대기...");
    delay(3000);
    connectWebSocket();
  }
}
