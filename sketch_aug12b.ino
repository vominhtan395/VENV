#include <SPI.h>
#include <MFRC522.h>
#include <Servo.h>

#define CHAN_RFID_SS   10
#define CHAN_RFID_RST  8
#define CHAN_SERVO     6      
#define CHAN_BUZZER    7    

const int  GOC_DONG     = 10;    
const int  GOC_MO       = 90;
const long OPEN_GIU_MS  = 5000;  
const long LOC_TRUNG_MS = 800;   
const bool TU_MO_THEO_WHITELIST = false;

const byte UID_HOP_LE[][4] = {
  {0xD3, 0x2F, 0x23, 0x2B}, // 82A-08123
  {0x33, 0x56, 0xF8, 0x13}  // 72A-99371
};
const uint8_t SO_UID_HOP_LE = sizeof(UID_HOP_LE) / 4;

MFRC522 rfid(CHAN_RFID_SS, CHAN_RFID_RST);
Servo   servoCong;

bool congDangMo = false;
unsigned long lucMo = 0;
unsigned long lucInUIDCuoi = 0;
byte uidCuoi[4] = {0,0,0,0};

void buzzerBip(int ms = 100) {
  digitalWrite(CHAN_BUZZER, LOW);
  delay(ms);
  digitalWrite(CHAN_BUZZER, HIGH);
}

void moCong() {
  servoCong.write(GOC_MO);
  congDangMo = true;
  lucMo = millis();
  buzzerBip(100);
}

void dongCong() {
  servoCong.write(GOC_DONG);
  congDangMo = false;
}

bool laUIDTrung(const byte a[4], const byte b[4]) {
  for (int i=0;i<4;i++) if (a[i]!=b[i]) return false;
  return true;
}

bool namTrongWhitelist(const byte u[4]) {
  for (uint8_t i=0;i<SO_UID_HOP_LE;i++){
    bool ok = true;
    for (uint8_t j=0;j<4;j++){
      if (u[j] != UID_HOP_LE[i][j]) { ok=false; break; }
    }
    if (ok) return true;
  }
  return false;
}

void inUIDHex(const byte u[4]) {
  Serial.print("UID:");
  for (int i=0;i<4;i++){
    if (u[i] < 0x10) Serial.print('0');
    Serial.print(u[i], HEX);
  }
  Serial.println(); 
}

void setup() {
  pinMode(CHAN_BUZZER, OUTPUT);
  digitalWrite(CHAN_BUZZER, HIGH); 

  servoCong.attach(CHAN_SERVO);
  dongCong();

  SPI.begin();
  rfid.PCD_Init();

  Serial.begin(115200);
  Serial.println("READY");
}

void loop() {
  if (rfid.PICC_IsNewCardPresent() && rfid.PICC_ReadCardSerial()) {
    byte u[4] = {0,0,0,0};
    for (byte i=0; i<rfid.uid.size && i<4; i++) u[i] = rfid.uid.uidByte[i];

    unsigned long now = millis();

    if (!(laUIDTrung(u, uidCuoi) && (now - lucInUIDCuoi < LOC_TRUNG_MS))) {
      inUIDHex(u);
      for (int i=0;i<4;i++) uidCuoi[i]=u[i];
      lucInUIDCuoi = now;
    }

    if (TU_MO_THEO_WHITELIST && namTrongWhitelist(u)) {
      moCong();
    }

    buzzerBip(60);

    rfid.PICC_HaltA();
    rfid.PCD_StopCrypto1();
  }

  while (Serial.available()) {
    String dong = Serial.readStringUntil('\n');
    dong.trim();
    if (dong == "OPEN") {
      moCong();
    } else if (dong == "CLOSE") {
      dongCong();
    } else if (dong == "RESET") {
      dongCong();
    }
  }

  if (congDangMo && (millis() - lucMo > OPEN_GIU_MS)) {
    dongCong();
  }

  delay(10);
}
