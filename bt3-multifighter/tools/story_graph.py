"""Editable event/action graph. Edges mean dependencies, not a false total order."""
from PySide6.QtCore import Qt,Signal,QPointF
from PySide6.QtGui import QColor,QPen,QBrush,QPainter,QPainterPath,QFont
from PySide6.QtWidgets import (QWidget,QVBoxLayout,QHBoxLayout,QPushButton,QLabel,
    QGraphicsView,QGraphicsScene,QGraphicsRectItem,QGraphicsTextItem,QGraphicsItem)


def references(c):
    if c.get('type') in ('event','event_failed'):return {c['event']}
    if c.get('type')=='not':return references(c['condition'])
    return set().union(*(references(child) for child in c.get('conditions',[])))


def action_label(a):
    from character_names import character_name
    k=a['type'];who=a.get('fighter','')
    if k=='cinematic':
        anim=a.get('animation');voice=a.get('voice')
        return (f"{who} · Cinematic · {a.get('seconds',4):g}s\n"+
                (f"{character_name(anim['character'])} animation {anim['clip']}" if anim else 'Camera-only shot')+
                (f"\nVoice: {character_name(voice['character'])} / {voice['line']}" if voice else ''))
    if k=='wait':return f"{'Frozen pause' if a.get('freeze') else 'Battle continues'} · {a['seconds']:g}s"
    if k=='set_stats':return who+' · Change stats\n'+', '.join(f'{k}={v}' for k,v in a['stats'].items())
    if k=='take_control':return f"Player {a['player']} now controls {who}"
    if k=='target':return f"{who} targets {a['target']}"
    if k=='voice':return f"{who} · Voice {a['line']}\n{character_name(a['character'])}"
    if k=='transform':return f"{who} → {character_name(a['character'])}"
    if k in ('recover','heal','enter'):return f"{who} · {k.title()} · {a.get('health_percent',100):g}% HP"
    if k=='message':return f"Message · {a.get('seconds',4):g}s\n{a['text']}"
    return f'{who} · {k.title()}'


class Node(QGraphicsRectItem):
    def __init__(self,graph,event,action,text,x,y,width,height,color):
        super().__init__(0,0,width,height);self.graph=graph;self.event=event;self.action=action
        self.setPos(x,y);self.setPen(QPen(QColor(color),1.5));self.setBrush(QBrush(QColor('#172334')))
        self.setFlag(QGraphicsItem.ItemIsSelectable);self.setToolTip(text+'\nDouble-click to edit')
        self.text=QGraphicsTextItem(text,self);self.text.setDefaultTextColor(QColor('#eff6ff'))
        self.text.setFont(QFont('Segoe UI',10));self.text.setTextWidth(width-20);self.text.setPos(8,5)
        self.text.setAcceptedMouseButtons(Qt.NoButton)
        self.setRect(0,0,width,max(height,self.text.boundingRect().height()+10))
    def mousePressEvent(self,e):
        super().mousePressEvent(e);self.graph.selected.emit(self.event,self.action)
    def mouseDoubleClickEvent(self,e):
        self.graph.activated.emit(self.event,self.action);e.accept()


class GraphView(QGraphicsView):
    def wheelEvent(self,event):
        if event.modifiers()&Qt.ControlModifier:
            scale=1.15 if event.angleDelta().y()>0 else 1/1.15
            if .25<=self.transform().m11()*scale<=2.5:self.scale(scale,scale)
            event.accept()
        else:super().wheelEvent(event)


class EventGraph(QWidget):
    selected=Signal(int,int)
    activated=Signal(int,int)
    def __init__(self,parent=None):
        super().__init__(parent);layout=QVBoxLayout(self);layout.setContentsMargins(0,0,0,0)
        row=QHBoxLayout();layout.addLayout(row)
        note=QLabel('Triggers → ordered actions → dependent events. Separate branches may run independently. Double-click any node to edit.');note.setWordWrap(True);row.addWidget(note,1)
        fit=QPushButton('Fit');fit.clicked.connect(self.fit);row.addWidget(fit)
        actual=QPushButton('100%');actual.clicked.connect(lambda:self.view.resetTransform());row.addWidget(actual)
        self.scene=QGraphicsScene(self);self.view=GraphView(self.scene);self.view.setRenderHint(QPainter.Antialiasing)
        self.view.setBackgroundBrush(QColor('#0b1420'));self.view.setDragMode(QGraphicsView.ScrollHandDrag)
        self.view.setMinimumHeight(300);layout.addWidget(self.view);self.nodes=[];self.event_nodes={};self.document=None
    def fit(self):
        self.view.fitInView(self.scene.itemsBoundingRect().adjusted(-16,-16,16,16),Qt.KeepAspectRatio)
        if self.view.transform().m11()>1:self.view.resetTransform()
    def edge(self,start,end,color='#4f728c'):
        p=QPainterPath(start);middle=(start.y()+end.y())/2
        p.cubicTo(start.x(),middle,end.x(),middle,end.x(),end.y());self.scene.addPath(p,QPen(QColor(color),2))
        # Downward arrow at the destination.
        p=QPainterPath(end+QPointF(-4,-7));p.lineTo(end);p.lineTo(end+QPointF(4,-7));self.scene.addPath(p,QPen(QColor(color),2))
    def dependency_edge(self,start,end):
        middle=(start.x()+end.x())/2;p=QPainterPath(start)
        p.cubicTo(middle,start.y(),middle,end.y(),end.x(),end.y());pen=QPen(QColor('#f2c777'),2)
        self.scene.addPath(p,pen)
        p=QPainterPath(end+QPointF(-7,-4));p.lineTo(end);p.lineTo(end+QPointF(-7,4));self.scene.addPath(p,pen)
    def set_document(self,document):
        from story_editor import condition_label
        self.document=document;self.scene.clear();self.nodes=[];self.event_nodes={};events=document['events']
        if not events:
            self.scene.addText('No events yet. Add an event to create a trigger and its action sequence.').setDefaultTextColor(QColor('#edf5ff'));return
        byid={e['id']:i for i,e in enumerate(events)};deps=[references(e['when']) for e in events];depth={}
        def level(i,path=frozenset()):
            if i in depth:return depth[i]
            if i in path:return 0 # Invalid cycles remain visible and editable; Validate explains them.
            depth[i]=max((level(byid[n],path|{i})+1 for n in deps[i] if n in byid and byid[n] not in path|{i}),default=0)
            return depth[i]
        columns={};ends={};starts={}
        for i,event in enumerate(events):
            column=level(i);x=column*400+20;y=columns.get(column,20)
            header=f"{event['id']}\nWHEN {condition_label(event['when'])}\nWait timeout: {event.get('timeout_seconds',30):g}s"
            h=100;node=Node(self,i,-1,header,x,y,340,h,'#52b9f7');self.scene.addItem(node);self.nodes.append(node);self.event_nodes[i]=node
            starts[i]=QPointF(x,y+node.rect().height()/2);y+=node.rect().height();previous=QPointF(x+170,y)
            for k,action in enumerate(event['actions']):
                y+=24;text=f'{k+1}. '+action_label(action);height=92 if action['type']=='cinematic' else 68
                self.edge(previous,QPointF(x+170,y));node=Node(self,i,k,text,x+10,y,320,height,'#5acd9c');self.scene.addItem(node);self.nodes.append(node)
                y+=node.rect().height();previous=QPointF(x+170,y)
            ends[i]=QPointF(node.x()+node.rect().width(),node.y()+node.rect().height()/2);columns[column]=y+74
        for i,names in enumerate(deps):
            for name in names:
                if name in byid:self.dependency_edge(ends[byid[name]],starts[i])
        self.scene.setSceneRect(self.scene.itemsBoundingRect().adjusted(-20,-20,20,20))
    def show_status(self,state):
        statuses={e['id']:e for e in (state or {}).get('events',[])}
        colors={'waiting':'#52b9f7','running':'#ffce64','complete':'#5acd9c','failed':'#ff7885'}
        if self.document:
            for node in self.nodes:
                info=statuses.get(self.document['events'][node.event]['id'],{});status=info.get('status','waiting')
                if node.action>=0 and status in ('running','failed'):
                    step=info.get('action_index',0)
                    if node.action<step:status='complete'
                    elif node.action>step:status='waiting'
                node.setPen(QPen(QColor(colors[status]),2.5))
