#!/usr/bin/env python3
"""Generate a very legible logic-symbol schematic for U1/SN74AHCT125N."""
from pathlib import Path
import html

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "diagrams"
OUT.mkdir(parents=True, exist_ok=True)
SVG = OUT / "esp32-led-controller-v6-u1-ahct125-schematic.svg"
PNG = OUT / "esp32-led-controller-v6-u1-ahct125-schematic.png"
W, H = 2000, 1350
C = {
    "bg": "#fbfbfb", "ink": "#111827", "muted": "#64748b", "box": "#ffffff",
    "u1": "#5b21b6", "u1fill": "#f3e8ff", "data": "#d97706", "p5": "#be185d",
    "gnd": "#111827", "green": "#047857", "warn": "#b45309", "blue": "#2563eb",
    "light": "#f8fafc", "grid": "#e2e8f0",
}

def e(s): return html.escape(str(s), quote=True)
parts = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}">', f'<rect width="100%" height="100%" fill="{C["bg"]}"/>']
def add(s): parts.append(s)
def line(x1,y1,x2,y2,c="ink",w=4,dash=None):
    da=f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<line x1="{x1}" y1="{y1}" x2="{x2}" y2="{y2}" stroke="{C.get(c,c)}" stroke-width="{w}" stroke-linecap="round" fill="none"{da}/>')
def poly(points,c="ink",w=4,fill="none",dash=None):
    da=f' stroke-dasharray="{dash}"' if dash else ""
    add(f'<polyline points="{" ".join(f"{x},{y}" for x,y in points)}" stroke="{C.get(c,c)}" stroke-width="{w}" stroke-linecap="round" stroke-linejoin="round" fill="{fill}"{da}/>')
def rect(x,y,w,h,fill="box",stroke="ink",sw=3,rx=14):
    add(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="{rx}" fill="{C.get(fill,fill)}" stroke="{C.get(stroke,stroke)}" stroke-width="{sw}"/>')
def text(x,y,s,size=24,c="ink",weight=400,anchor="start"):
    add(f'<text x="{x}" y="{y}" fill="{C.get(c,c)}" font-family="Inter,Arial,Helvetica,sans-serif" font-size="{size}" font-weight="{weight}" text-anchor="{anchor}">{e(s)}</text>')
def circle(x,y,r=7,c="ink"):
    add(f'<circle cx="{x}" cy="{y}" r="{r}" fill="{C.get(c,c)}" stroke="{C.get(c,c)}" stroke-width="2"/>')
def gnd(x,y,label=None):
    line(x,y,x,y+14,"gnd",4); line(x-24,y+14,x+24,y+14,"gnd",4); line(x-16,y+25,x+16,y+25,"gnd",4); line(x-8,y+36,x+8,y+36,"gnd",4)
    if label: text(x+34,y+29,label,19,"gnd",700)
def p5_flag(x,y,label="+5 V"):
    line(x,y,x,y-24,"p5",4)
    add(f'<polygon points="{x},{y-48} {x-22},{y-24} {x+22},{y-24}" fill="{C["p5"]}" stroke="{C["p5"]}" stroke-width="2"/>')
    text(x+34,y-26,label,19,"p5",800)
def resistor(x1,y,x2,label):
    mid=(x1+x2)/2
    line(x1,y,mid-52,y,"data",4); rect(mid-52,y-20,104,40,fill="#fff7ed",stroke="data",sw=3,rx=8); line(mid+52,y,x2,y,"data",4)
    text(mid,y-31,label,20,"data",800,"middle")
def buffer_symbol(x,y,label,input_pin,output_pin,oe_pin,oe_text,enabled=True):
    add(f'<polygon points="{x},{y-42} {x},{y+42} {x+105},{y}" fill="{C["u1fill"]}" stroke="{C["u1"]}" stroke-width="4"/>')
    text(x+48,y+8,label,22,"u1",800,"middle")
    line(x-90,y,x,y,"data" if enabled else "gnd",4)
    line(x+105,y,x+195,y,"data" if enabled else "muted",4 if enabled else 3,dash=None if enabled else "8 8")
    text(x-100,y-12,input_pin,20,"data" if enabled else "gnd",800,"end")
    text(x+205,y-12,output_pin,20,"data" if enabled else "muted",800)
    line(x+44,y+64,x+44,y+118,"gnd" if enabled else "p5",4)
    circle(x+44,y+58,7,"u1")
    text(x+62,y+103,oe_pin,19,"gnd" if enabled else "p5",800)
    text(x+62,y+128,oe_text,18,"gnd" if enabled else "p5",700)

# Title
text(70,70,"ESP32 LED Controller v6 — SN74AHCT125N proper schematic",42,"ink",800)
text(70,116,"Answer: pins 10 and 13 go to +5 V, not GND, when channels 3/4 are unused and should be disabled.",29,"warn",800)
text(70,153,"Reason: /OE is active-low. LOW/GND enables a buffer; HIGH/+5 V disables output to high-Z.",24,"muted",700)

# Rails
line(90,220,1910,220,"p5",7); text(105,203,"P5_LOGIC_USB  +5 V from ESP32 USB/VIN only",24,"p5",800)
line(90,1210,1910,1210,"gnd",7); text(105,1193,"GND_COMMON",24,"gnd",800)

# Used channels
rect(70,260,1180,420,fill="#fff",stroke="#fed7aa",sw=3,rx=18)
text(95,305,"Used buffers — enabled",28,"data",800)
text(105,382,"ESP32 GPIO25",22,"blue",800); line(265,374,400,374,"data",4)
buffer_symbol(490,374,"1","pin 2 / 1A","pin 3 / 1Y","pin 1 /OE1","GND enables",True)
line(400,374,400,374,"data",4)
resistor(790,374,1040,"R1 470Ω"); text(1070,382,"J1 DATA",23,"green",800)
text(105,542,"ESP32 GPIO26",22,"blue",800); line(265,534,400,534,"data",4)
buffer_symbol(490,534,"2","pin 5 / 2A","pin 6 / 2Y","pin 4 /OE2","GND enables",True)
resistor(790,534,1040,"R2 470Ω"); text(1070,542,"J2 DATA",23,"green",800)
gnd(534,492,"pin 1 /OE1")
gnd(534,652,"pin 4 /OE2")

# Unused buffers
rect(70,715,1180,330,fill="#fff",stroke="#cbd5e1",sw=3,rx=18)
text(95,760,"Unused buffers — disabled, outputs left NC",28,"u1",800)
text(105,838,"pin 9 / 3A",22,"gnd",800); line(260,830,400,830,"gnd",4); gnd(245,842)
buffer_symbol(490,830,"3","pin 9 / 3A","pin 8 / 3Y = NC","pin 10 /OE3","+5 V disables",False)
p5_flag(534,948,"pin 10 /OE3")
text(105,988,"pin 12 / 4A",22,"gnd",800); line(260,980,400,980,"gnd",4); gnd(245,992)
buffer_symbol(490,980,"4","pin 12 / 4A","pin 11 / 4Y = NC","pin 13 /OE4","+5 V disables",False)
p5_flag(534,1098,"pin 13 /OE4")
text(865,838,"NC — no wire",22,"muted",800)
text(865,988,"NC — no wire",22,"muted",800)

# Power pins + decoupling
rect(1310,260,610,360,fill="#fff",stroke="#bfdbfe",sw=3,rx=18)
text(1335,305,"Power pins + decoupling",28,"blue",800)
text(1350,370,"U1 pin 14 VCC",23,"p5",800); line(1540,362,1765,362,"p5",4); line(1765,362,1765,220,"p5",4); circle(1765,220,7,"p5")
text(1350,430,"U1 pin 7 GND",23,"gnd",800); line(1540,422,1765,422,"gnd",4); line(1765,422,1765,1210,"gnd",4); circle(1765,1210,7,"gnd")
rect(1365,485,500,80,fill="#f8fafc",stroke="#cbd5e1",sw=2,rx=10)
text(1385,518,"C2 0.1µF directly at pin 14 ↔ pin 7",20,"ink",700)
text(1385,548,"C3 10µF nearby across same rails",20,"muted",600)

# Pin table
rect(1310,660,610,385,fill="#fff",stroke="#cbd5e1",sw=3,rx=18)
text(1335,705,"Continuity / wiring table",28,"ink",800)
rows=[("1 /OE1","GND","enable ch1"),("4 /OE2","GND","enable ch2"),("10 /OE3","+5 V","disable ch3"),("13 /OE4","+5 V","disable ch4"),("9 /3A","GND","unused input low"),("12 /4A","GND","unused input low"),("8 /3Y","NC","leave open"),("11 /4Y","NC","leave open")]
y=745
for i,(pin,net,why) in enumerate(rows):
    fill="#f8fafc" if i%2==0 else "#ffffff"
    rect(1335,y-24,540,34,fill=fill,stroke="#e2e8f0",sw=1,rx=5)
    text(1350,y,pin,19,"ink",800)
    text(1480,y,net,19,"p5" if net=="+5 V" else "gnd" if net=="GND" else "muted",800)
    text(1590,y,why,19,"muted",600)
    y+=39

rect(1310,1080,610,85,fill="#fff7ed",stroke="warn",sw=3,rx=18)
text(1335,1120,"Do not tie pins 10/13 to GND if the goal is to disable unused channels.",23,"warn",800)
text(1335,1150,"GND would enable them; +5 V is the clean high-Z state.",21,"ink",700)

parts.append('</svg>')
SVG.write_text('\n'.join(parts), encoding='utf-8')

try:
    from PIL import Image, ImageDraw, ImageFont
    img=Image.new('RGB',(W,H),C['bg']); d=ImageDraw.Draw(img)
    try:
        fb=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',42)
        fh=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial Bold.ttf',30)
        f=ImageFont.truetype('/System/Library/Fonts/Supplemental/Arial.ttf',24)
    except Exception:
        fb=fh=f=ImageFont.load_default()
    d.rounded_rectangle((45,45,W-45,H-45),radius=28,fill='white',outline='#cbd5e1',width=4)
    d.text((90,95),'SN74AHCT125N /OE pin answer',fill=C['ink'],font=fb)
    d.text((90,160),'Pins 10 and 13 go to +5 V to disable unused channels 3 and 4.',fill=C['warn'],font=fh)
    d.text((90,215),'/OE is active-low: GND enables; +5 V disables/high-Z.',fill=C['muted'],font=f)
    rows=[('1 /OE1','GND','enable channel 1'),('4 /OE2','GND','enable channel 2'),('10 /OE3','+5 V','disable unused channel 3'),('13 /OE4','+5 V','disable unused channel 4'),('9 /3A','GND','unused input low'),('12 /4A','GND','unused input low'),('8 /3Y','NC','leave open'),('11 /4Y','NC','leave open')]
    y=310
    for pin,net,why in rows:
        color=C['p5'] if net=='+5 V' else C['gnd'] if net=='GND' else C['muted']
        d.rounded_rectangle((100,y,1900,y+72), radius=12, fill='#f8fafc', outline='#e2e8f0')
        d.text((140,y+19),pin,fill=C['ink'],font=fh)
        d.text((450,y+19),net,fill=color,font=fh)
        d.text((700,y+22),why,fill=C['muted'],font=f)
        y+=88
    d.text((100,1110),'Used data: GPIO25 → pin 2 → pin 3 → R1 → J1 DATA; GPIO26 → pin 5 → pin 6 → R2 → J2 DATA.',fill=C['data'],font=f)
    img.save(PNG)
except Exception as ex:
    PNG.write_text(f'PNG generation skipped: {ex}\n')
print(SVG)
print(PNG)
