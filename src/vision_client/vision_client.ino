/*
 * ============================================
 *  XIAO ESP32-S3 Sense + DFR0954
 *  WiFi 인터넷 라디오 + 시리얼 명령 컨트롤
 * ============================================
 *
 *  배선:
 *    DFR0954 VCC  → XIAO VUSB
 *    DFR0954 GND  → XIAO GND
 *    DFR0954 LRC  → XIAO D0  (GPIO1)
 *    DFR0954 BCLK → XIAO D1  (GPIO2)
 *    DFR0954 DIN  → XIAO D2  (GPIO3)
 *    버튼         → XIAO D3 ↔ GND
 *
 *  필수 라이브러리: ESP32-audioI2S by schreibfaul1
 *  필수 보드 설정:
 *    PSRAM: OPI PSRAM
 *    Partition Scheme: Huge APP (3MB No OTA/1MB SPIFFS)
 *
 *  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *  📟 시리얼 명령어 (Serial Monitor에 입력):
 *  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 *    v <0-21>   : 음량 설정      (예: v 15)
 *    +          : 음량 +1
 *    -          : 음량 -1
 *    n          : 다음 채널
 *    p          : 이전 채널
 *    c <번호>   : 특정 채널 선택  (예: c 2)
 *    s          : 정지
 *    r          : 재생 재개 (현재 채널)
 *    l          : 채널 목록 보기
 *    i          : 현재 상태 정보
 *    h          : 도움말
 *  ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
 */

#include <Arduino.h>
#include <WiFi.h>
#include "Audio.h"

// ─────────────────────────────────────
// 핀 정의
// ─────────────────────────────────────
#define PIN_I2S_LRC   1
#define PIN_I2S_BCLK  2
#define PIN_I2S_DIN   3
#define PIN_BUTTON    4

// ─────────────────────────────────────
// WiFi 설정
// ─────────────────────────────────────
const char* WIFI_SSID     = "TP-Link_ECA4";
const char* WIFI_PASSWORD = "92102071";

// ─────────────────────────────────────
// 라디오 채널 목록
// ─────────────────────────────────────
struct RadioStation {
  const char* url;
  const char* name;
};

const RadioStation STREAMS[] = {
  { "http://stream.live.vc.bbcmedia.co.uk/bbc_world_service",
    "BBC World Service" },
  { "http://ice1.somafm.com/groovesalad-128-mp3",
    "SomaFM Groove Salad (Chillout)" },
  { "http://ice1.somafm.com/lush-128-mp3",
    "SomaFM Lush (Vocal Chill)" },
  { "http://ice1.somafm.com/dronezone-128-mp3",
    "SomaFM Drone Zone (Ambient)" },
};

const int STREAM_COUNT = sizeof(STREAMS) / sizeof(STREAMS[0]);
int currentStream = 0;

// ─────────────────────────────────────
// 오디오 / 상태 변수
// ─────────────────────────────────────
Audio audio;

#define DEFAULT_VOLUME  10
#define VOLUME_MIN      0
#define VOLUME_MAX      21

int  currentVolume = DEFAULT_VOLUME;
bool isPlaying     = false;

// 버튼 디바운싱
unsigned long lastPressTime = 0;
const unsigned long DEBOUNCE_MS = 500;

// 시리얼 입력 버퍼
String serialBuffer = "";

// ============================================
// WiFi 연결
// ============================================
void connectWiFi() {
  Serial.print("WiFi 연결 중 [");
  Serial.print(WIFI_SSID);
  Serial.print("] ");

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);

  int retry = 0;
  while (WiFi.status() != WL_CONNECTED && retry < 30) {
    delay(500);
    Serial.print(".");
    retry++;
  }

  if (WiFi.status() == WL_CONNECTED) {
    Serial.println(" ✅ 연결됨!");
    Serial.print("IP 주소: ");
    Serial.println(WiFi.localIP());
    Serial.print("신호 강도: ");
    Serial.print(WiFi.RSSI());
    Serial.println(" dBm");
  } else {
    Serial.println(" ❌ 연결 실패!");
  }
}

// ============================================
// 스트림 재생
// ============================================
void playStream(int index) {
  if (index < 0 || index >= STREAM_COUNT) {
    Serial.println("❌ 잘못된 채널 번호!");
    return;
  }

  currentStream = index;
  isPlaying = true;

  Serial.println("─────────────────────────────");
  Serial.print("🎵 [채널 ");
  Serial.print(index);
  Serial.print("] ");
  Serial.println(STREAMS[index].name);
  Serial.print("   URL: ");
  Serial.println(STREAMS[index].url);
  Serial.println("─────────────────────────────");

  audio.stopSong();
  audio.connecttohost(STREAMS[index].url);
}

void nextStream() {
  int next = (currentStream + 1) % STREAM_COUNT;
  playStream(next);
}

void prevStream() {
  int prev = (currentStream - 1 + STREAM_COUNT) % STREAM_COUNT;
  playStream(prev);
}

// ============================================
// 음량 설정
// ============================================
void setVolume(int vol) {
  // 범위 제한
  if (vol < VOLUME_MIN) vol = VOLUME_MIN;
  if (vol > VOLUME_MAX) vol = VOLUME_MAX;

  currentVolume = vol;
  audio.setVolume(currentVolume);

  // 음량 시각화 막대 (▮▮▮▮▮▯▯▯▯▯)
  Serial.print("🔊 음량: ");
  Serial.print(currentVolume);
  Serial.print("/");
  Serial.print(VOLUME_MAX);
  Serial.print("  [");

  int bars = map(currentVolume, 0, VOLUME_MAX, 0, 21);
  for (int i = 0; i < 21; i++) {
    Serial.print(i < bars ? "▮" : "▯");
  }
  Serial.println("]");
}

// ============================================
// 정지 / 재생
// ============================================
void stopAudio() {
  audio.stopSong();
  isPlaying = false;
  Serial.println("⏸️  정지됨");
}

void resumeAudio() {
  if (!isPlaying) {
    Serial.println("▶️  재생 재개...");
    playStream(currentStream);
  } else {
    Serial.println("이미 재생 중입니다.");
  }
}

// ============================================
// 채널 목록 출력
// ============================================
void printChannelList() {
  Serial.println("\n📻 채널 목록:");
  Serial.println("─────────────────────────────");
  for (int i = 0; i < STREAM_COUNT; i++) {
    Serial.print(i == currentStream ? " ▶ " : "   ");
    Serial.print("[");
    Serial.print(i);
    Serial.print("] ");
    Serial.println(STREAMS[i].name);
  }
  Serial.println("─────────────────────────────\n");
}

// ============================================
// 현재 상태 출력
// ============================================
void printStatus() {
  Serial.println("\n📊 현재 상태:");
  Serial.println("─────────────────────────────");
  Serial.print("  상태  : ");
  Serial.println(isPlaying ? "▶️  재생 중" : "⏸️  정지");
  Serial.print("  채널  : [");
  Serial.print(currentStream);
  Serial.print("] ");
  Serial.println(STREAMS[currentStream].name);
  Serial.print("  음량  : ");
  Serial.print(currentVolume);
  Serial.print("/");
  Serial.println(VOLUME_MAX);
  Serial.print("  WiFi  : ");
  Serial.print(WiFi.RSSI());
  Serial.println(" dBm");
  Serial.print("  IP    : ");
  Serial.println(WiFi.localIP());
  Serial.println("─────────────────────────────\n");
}

// ============================================
// 도움말 출력
// ============================================
void printHelp() {
  Serial.println("\n📖 사용 가능한 명령어:");
  Serial.println("─────────────────────────────");
  Serial.println("  v <0-21>  : 음량 설정 (예: v 15)");
  Serial.println("  +         : 음량 +1");
  Serial.println("  -         : 음량 -1");
  Serial.println("  n         : 다음 채널");
  Serial.println("  p         : 이전 채널");
  Serial.println("  c <번호>  : 특정 채널 선택 (예: c 2)");
  Serial.println("  s         : 정지");
  Serial.println("  r         : 재생 재개");
  Serial.println("  l         : 채널 목록 보기");
  Serial.println("  i         : 현재 상태 정보");
  Serial.println("  h         : 도움말 (이 화면)");
  Serial.println("─────────────────────────────\n");
}

// ============================================
// 시리얼 명령 처리
// ============================================
void handleCommand(String cmd) {
  cmd.trim();           // 앞뒤 공백 제거
  if (cmd.length() == 0) return;

  Serial.print("\n>> 명령: ");
  Serial.println(cmd);

  // 첫 글자로 명령 분류
  char c = cmd.charAt(0);

  switch (c) {

    // 음량 설정: "v 15"
    case 'v':
    case 'V': {
      if (cmd.length() > 2) {
        int vol = cmd.substring(2).toInt();
        setVolume(vol);
      } else {
        Serial.println("❓ 사용법: v <0-21>  예) v 15");
      }
      break;
    }

    // 음량 +1
    case '+':
      setVolume(currentVolume + 1);
      break;

    // 음량 -1
    case '-':
      setVolume(currentVolume - 1);
      break;

    // 다음 채널
    case 'n':
    case 'N':
      nextStream();
      break;

    // 이전 채널
    case 'p':
    case 'P':
      prevStream();
      break;

    // 특정 채널: "c 2"
    case 'c':
    case 'C': {
      if (cmd.length() > 2) {
        int ch = cmd.substring(2).toInt();
        playStream(ch);
      } else {
        Serial.println("❓ 사용법: c <채널번호>  예) c 2");
      }
      break;
    }

    // 정지
    case 's':
    case 'S':
      stopAudio();
      break;

    // 재생 재개
    case 'r':
    case 'R':
      resumeAudio();
      break;

    // 채널 목록
    case 'l':
    case 'L':
      printChannelList();
      break;

    // 상태 정보
    case 'i':
    case 'I':
      printStatus();
      break;

    // 도움말
    case 'h':
    case 'H':
    case '?':
      printHelp();
      break;

    default:
      Serial.print("❓ 알 수 없는 명령: ");
      Serial.println(cmd);
      Serial.println("   'h' 입력해서 도움말 확인하세요.");
      break;
  }
}

// ============================================
// 시리얼 입력 읽기 (논블로킹)
//   엔터(\n)가 들어올 때까지 글자 모으기
// ============================================
void readSerialInput() {
  while (Serial.available() > 0) {
    char c = Serial.read();

    if (c == '\n' || c == '\r') {
      // 엔터 → 명령 실행
      if (serialBuffer.length() > 0) {
        handleCommand(serialBuffer);
        serialBuffer = "";
      }
    } else {
      // 일반 글자 → 버퍼에 추가
      serialBuffer += c;
    }
  }
}

// ============================================
// 초기 설정
// ============================================
void setup() {
  Serial.begin(115200);
  delay(1000);

  Serial.println("\n========================================");
  Serial.println("  XIAO ESP32-S3 + DFR0954 라디오");
  Serial.println("  (시리얼 명령 컨트롤 버전)");
  Serial.println("========================================");

  // 버튼 설정
  pinMode(PIN_BUTTON, INPUT_PULLUP);

  // WiFi 연결
  connectWiFi();
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi 없이는 동작 불가. 정지.");
    while (1) delay(1000);
  }

  // 오디오 초기화
  audio.setPinout(PIN_I2S_BCLK, PIN_I2S_LRC, PIN_I2S_DIN);
  audio.setVolume(currentVolume);

  // 안내 메시지
  Serial.println("\n[준비 완료]");
  Serial.println("  • 버튼: 다음 채널");
  Serial.println("  • 시리얼: 'h' 입력해서 명령어 확인");
  Serial.println();

  // 첫 채널 자동 재생
  playStream(currentStream);
}

// ============================================
// 메인 루프
// ============================================
void loop() {
  // 1. 오디오 처리 (필수, 끊김없이 호출)
  audio.loop();

  // 2. 시리얼 입력 처리
  readSerialInput();

  // 3. 버튼 처리 (다음 채널)
  if (digitalRead(PIN_BUTTON) == LOW) {
    unsigned long now = millis();
    if (now - lastPressTime > DEBOUNCE_MS) {
      lastPressTime = now;
      Serial.println("\n[🔘 버튼] 다음 채널");
      nextStream();
    }
  }

  // 4. WiFi 끊김 감지 시 재연결
  if (WiFi.status() != WL_CONNECTED) {
    Serial.println("WiFi 끊김. 재연결 시도...");
    connectWiFi();
  }
}

// ============================================
// 오디오 라이브러리 콜백
// ============================================
void audio_showstreamtitle(const char *info) {
  Serial.print("📻 지금 재생: ");
  Serial.println(info);
}

void audio_showstation(const char *info) {
  Serial.print("📡 방송국: ");
  Serial.println(info);
}

void audio_bitrate(const char *info) {
  Serial.print("🎚️  비트레이트: ");
  Serial.println(info);
}