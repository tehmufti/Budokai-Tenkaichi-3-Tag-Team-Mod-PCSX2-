"""Sparse synthetic EE machine for policy tests; no disc or captured RAM."""
from test_ai_shadow import Mips
from native_map import GP

MANAGER,BATTLE,CINE=0x1800000,0x1810000,0x1830000
ACTORS=tuple(0x2000000+i*0x2000 for i in range(6))
MODELS=tuple(0x3000000+i*0x2000 for i in range(6))


class Cpu(Mips):
    instruction_budget=200000
    fcr31=0
    hi=0
    lo=0

    def __init__(self,manifest):
        super().__init__(manifest)
        self.r[28]=GP
        self.f=[0]*32

    def extra_instruction(self,ins,pc):
        op,rs,rt=ins>>26,(ins>>21)&31,(ins>>16)&31
        imm=ins&65535;imm=imm if imm<32768 else imm-65536
        if op in (30,31):
            address=(self.r[rs]+imm)&0xFFFFFFFF
            if op==31:self.write(address,(self.r[rt]&((1<<128)-1)).to_bytes(16,'little'))
            else:self.r[rt]=int.from_bytes(self.read(address,16),'little')
        elif op==0 and ins&63==2:
            self.r[(ins>>11)&31]=(self.r[rt]&0xFFFFFFFF)>>((ins>>6)&31)
        elif op==49:self.f[rt]=self.u(self.r[rs]+imm)
        elif op==57:self.w(self.r[rs]+imm,self.f[rt])
        elif op==17 and rs==2:self.r[rt]=self.fcr31
        elif op==17 and rs==6:self.fcr31=self.r[rt]
        elif op==0 and ins&63 in (16,18):self.r[(ins>>11)&31]=self.hi if ins&63==16 else self.lo
        elif op==0 and ins&63==17:self.hi=self.r[rs]
        elif op==0 and ins&63==19:self.lo=self.r[rs]
        else:return super().extra_instruction(ins,pc)
