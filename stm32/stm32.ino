/* ============================================================
 *  ATSIQUE CanSat — STM32 Master Telemetry (Mock Data)
 *  Hardware: Nucleo F411RE
 *  Connection: USART1 (PA9=TX, PA10=RX) -> CanMV K230
 * ============================================================ */

#include <Arduino.h>

// Use HardwareSerial 1 (PA9, PA10)
HardwareSerial SerialK230(PA10, PA9); 

unsigned long pkt_id = 0;
unsigned long last_tx = 0;
const int TX_INTERVAL = 2000;

void setup() {
  Serial.begin(115200);      // Debug to PC
  SerialK230.begin(115200);  // Data to K230
  delay(1000);
  Serial.println("[STM32] Telemetry Master Ready");
}

void loop() {
  if (millis() - last_tx > TX_INTERVAL) {
    last_tx = millis();
    pkt_id++;

    // ── Generate Mock Data ───────────────────────────────────
    float ax = -0.11 + (sin(millis() / 500.0) * 0.5);
    float ay = 0.03 + (cos(millis() / 500.0) * 0.5);
    float az = 9.81 + (sin(millis() / 1000.0) * 0.2);
    float temp = 30.6 + (sin(millis() / 5000.0) * 2.0);
    float pressure = 900.8 - (pkt_id * 0.05);
    float alt = 980.9 - (pkt_id * 1.5);
    float lat = 19.4326;
    float lon = -99.1332;

    // ── Build CSV String ─────────────────────────────────────
    // Format: id,ax,ay,az,gx,gy,gz,temp,pres,id,lat,lon,roll,pitch,alt,gps,rdy,tick
    String csv = String(pkt_id) + "," +
                 String(ax, 4) + "," + String(ay, 4) + "," + String(az, 4) + "," +
                 "0.0,0.0,0.0," +    // Mock Gyro
                 String(temp, 2) + "," + String(pressure, 2) + "," +
                 "112," +            // sensor_id
                 String(lat, 6) + "," + String(lon, 6) + "," +
                 "0.0,0.0," +        // Mock Roll/Pitch
                 String(alt, 2) + "," +
                 "1,1," +            // GPS flags
                 String(millis());

    // ── Send to K230 ────────────────────────────────────────
    SerialK230.println(csv);
    Serial.print("[TX -> K230]: ");
    Serial.println(csv);
  }

  // Check for response from K230 (e.g., feedback or ACK)
  if (SerialK230.available()) {
    String resp = SerialK230.readStringUntil('\n');
    Serial.print("[K230 says]: ");
    Serial.println(resp);
  }
}