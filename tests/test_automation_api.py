"""Full HTTP boundary tests using temporary databases, never customer records."""
from datetime import UTC, datetime, timedelta
import pytest
from fastapi.testclient import TestClient
from reigel.api import create_app
from team_auth import allow, login as team_login

@pytest.fixture
def system(tmp_path, monkeypatch):
    monkeypatch.setenv('REIGEL_ENV','local')
    monkeypatch.delenv('SITE_URL',raising=False)
    app=create_app(tmp_path/'automation.db')
    store=app.state.store
    admin=store.create_user({'name':'Equipo QA','email':'qa@example.test','password':'long-private-test-password','role':'admin'},bootstrap=True)
    store.update_user(admin['id'],{'public_booking':True,'work_days':list(range(7))},admin)
    return app,store,admin

def login(client):
    assert team_login(client, 'qa@example.test', 'long-private-test-password').status_code==200

def test_chat_http_cookie_isolation_origin_and_admin_scope(system):
    app,_,_=system
    with TestClient(app) as one, TestClient(app) as two:
        initial=one.get('/api/public/chat')
        assert initial.status_code==200 and 'HttpOnly' in initial.headers['set-cookie']
        assert 'SameSite=strict' in initial.headers['set-cookie']
        assert 'Path=/api/public/chat' in initial.headers['set-cookie']
        first=initial.json()['conversation_id']
        assert two.post('/api/public/chat',json={'text':'hola','request_id':'message-001'}).status_code==401
        assert two.get('/api/public/chat').json()['conversation_id']!=first
        assert one.post('/api/public/chat',json={'text':'hola','request_id':'message-001'},headers={'Origin':'https://evil.test'}).status_code==403
        assert one.get('/api/knowledge').status_code==401
        assert one.post('/api/knowledge/refresh',json={}).status_code==401
        assert one.get('/api/automation').status_code==401

def test_real_booking_via_http_idempotent_and_visible_to_staff(system):
    app,store,admin=system
    with TestClient(app) as visitor, TestClient(app) as staff:
        first=visitor.get('/api/public/chat').json()
        day=(datetime.now(UTC)+timedelta(days=2)).date().isoformat()
        slot=store.slots(admin['id'],day)['slots'][0]
        data={'name':'Cliente QA','email':'client@example.test','municipality':'Ponce','consent':True,'advisor_id':admin['id'],'start_at':slot['start_at'],'request_id':'booking-0001'}
        booked=visitor.post('/api/public/chat/book',json=data)
        assert booked.status_code==200,booked.text
        appointment=booked.json()['appointment']
        assert appointment['status']=='confirmed'
        assert visitor.post('/api/public/chat/book',json=data).json()['appointment']['id']==appointment['id']
        assert len(store.list_appointments(admin))==1
        assert store.list_leads(admin)[0]['stage']=='cita'
        login(staff)
        assert any(c['id']==first['conversation_id'] for c in staff.get('/api/conversations').json()['conversations'])
        sent=staff.post('/api/conversations/'+first['conversation_id']+'/messages',json={'text':'Te atiende el equipo. Esta respuesta quedó en tu chat.'})
        assert sent.status_code==200,sent.text
        received=visitor.get('/api/public/chat').json()
        assert received['mode']=='human' and 'Te atiende' in received['messages'][-1]['text']
        assert staff.patch('/api/appointments/'+appointment['id'],json={'status':'cancelled'}).status_code==200
        assert visitor.get('/api/public/chat').json()['appointment']['status']=='cancelled'

def test_optout_blocks_staff_send_and_ai_reactivation(system):
    app,_,_=system
    with TestClient(app) as visitor, TestClient(app) as staff:
        cid=visitor.get('/api/public/chat').json()['conversation_id']
        assert visitor.post('/api/public/chat',json={'text':'no me escriban','request_id':'stop-0001'}).json()['opted_out']
        login(staff)
        assert staff.post('/api/conversations/'+cid+'/messages',json={'text':'Continuemos'}).status_code==409
        assert staff.post('/api/conversations/'+cid+'/mode',json={'mode':'ai'}).status_code==409


def test_session_polling_does_not_exhaust_new_chat_quota(system):
    app,_,_=system
    with TestClient(app) as client:
        cid=client.get('/api/public/chat').json()['conversation_id']
        for _ in range(70):
            r=client.get('/api/public/chat')
            assert r.status_code==200 and r.json()['conversation_id']==cid
