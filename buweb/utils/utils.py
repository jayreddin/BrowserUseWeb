from logging import Logger


def fmtdict(msg:dict,indent:str=""):
    for k,v in msg.items():
        if isinstance(v,dict):
            yield f"{indent}{str(k)}:"
            yield from fmtdict(v,indent+"  ")
        else:
            yield f"{indent}{str(k)}: {str(v)}"

class dump:
    def __init__(self,logger:Logger|None):
        self.logger = logger

    def fmt(self, msg:str|dict):
        if isinstance(msg,dict):
            msg = "\n".join(fmtdict(msg))
        return msg

    def info(self,msg:str|dict):
        print(self.fmt(msg))

    def error(self,msg:str|dict):
        print(self.fmt(msg))

async def safe_close(item):
    try:
        await item.close() # 
    except:
        pass