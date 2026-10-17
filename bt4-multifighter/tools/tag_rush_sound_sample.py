"""Keep a full-length non-looping PS2 sound within the private SPU budget."""
import math

COEFFICIENTS=((0,0),(60,0),(115,-52),(98,-55),(122,-60))


def decode(data):
    if not data or len(data)%16:raise ValueError('Invalid PS2 ADPCM sample')
    samples=[];s1=s2=0
    for at in range(0,len(data),16):
        shift=data[at]&15;predictor=data[at]>>4
        if predictor>=len(COEFFICIENTS)or shift>12:raise ValueError('Unsupported PS2 ADPCM block')
        if data[at+1]==7:break
        c1,c2=COEFFICIENTS[predictor]
        for byte in data[at+2:at+16]:
            for nibble in (byte&15,byte>>4):
                value=nibble if nibble<8 else nibble-16
                value=max(-32768,min(32767,((value<<12)>>shift)+((s1*c1+s2*c2+32)>>6)))
                samples.append(value);s2,s1=s1,value
    return samples


def at_rate(data,source_rate,target_rate):
    """Resample the whole effect, keeping its pitch/duration through VAG rate.

    Only the long explosion uses this. Beams and charge samples stay native;
    this avoids cutting the explosion short or taking SPU space from voices.
    """
    if not 8000<=target_rate<=source_rate<=48000:raise ValueError('Invalid private effect sample rate')
    import numpy as np
    source=decode(data);count=round(len(source)*target_rate/source_rate)
    wave=np.interp(np.arange(count)*source_rate/target_rate,np.arange(len(source)),source)
    result=bytearray();s1=s2=0
    for at in range(0,count,28):
        block=list(wave[at:at+28]);block.extend([0.]*(28-len(block)));best=None
        for predictor,(c1,c2)in enumerate(COEFFICIENTS):
            # Test the available quantizers using the reconstructed history,
            # exactly as the console decoder does (not the original PCM).
            for shift in range(13):
                p1,p2=s1,s2;error=0.;nibbles=[]
                for value in block:
                    predicted=(p1*c1+p2*c2+32)>>6
                    q=max(-8,min(7,int(round((value-predicted)*(1<<shift)/4096))))
                    restored=max(-32768,min(32767,((q<<12)>>shift)+predicted))
                    error+=(value-restored)**2;nibbles.append(q&15);p2,p1=p1,restored
                if best is None or error<best[0]:best=(error,predictor,shift,nibbles,p1,p2)
        _,predictor,shift,nibbles,s1,s2=best
        result.extend((predictor<<4|shift,1 if at+28>=count else 0))
        result.extend(nibbles[i]|nibbles[i+1]<<4 for i in range(0,28,2))
    result.extend(bytes.fromhex('07007777777777777777777777777777'))
    return bytes(result)
