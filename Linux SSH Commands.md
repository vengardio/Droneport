---
type: software
status: active
---
# SSH
## Подключение 
- Подключение с компа в OrangePI, находящуюся внутри одной локальной сети с компом
```
ssh droneport@OrangePiDronePort
```  
## Отправка файлов
- Отправка всего каталога с Windows на OrangePi
```
scp -r -P 22 "D:\Home folder\02 Projects\Droneport\Software\OrangePi\drone_gateway" droneport@OrangePiDronePort:/home/droneport/
```

# Orange Pi
## Листинг USART 
```python
python3 -c "
import serial
PORT='/dev/ttyS3'
BAUD=115200
ser=serial.Serial(PORT,BAUD,timeout=1)
print(f'Слушаю {PORT} @ {BAUD}...')
while True:
 data=ser.read(64)
 if data:print(f'[{len(data)}]',' '.join(f'{b}' for b in data))

```


---
[[Droneport_about]]
