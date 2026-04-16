import socket

HOST = '192.168.169.1'
PORT = 5000

print(f"Conectando a {HOST}:{PORT}...")

try:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.connect((HOST, PORT))
        print("✅ Conectado. Descargando imagen...")
        
        datos_imagen = bytearray()
        
        # Recibir todos los datos hasta que la K230 cierre la conexión
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            datos_imagen.extend(chunk)
            
    # Guardar archivo
    nombre = "foto_unica.jpg"
    with open(nombre, 'wb') as f:
        f.write(datos_imagen)
        
    print(f"🎉 ¡Éxito! Imagen guardada como '{nombre}' ({len(datos_imagen)} bytes).")

except Exception as e:
    print(f"Error: {e}")