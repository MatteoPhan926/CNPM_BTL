"""Count document writes at SQLite's boundary and check their persisted effects."""
import tempfile
import unittest
from pathlib import Path

from emobility.domain import DomainError, Service


ALICE = {'id': 'alice', 'role': 'student'}
OPERATOR = {'id': 'operator', 'role': 'operator'}


class DocumentWriteTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.path = Path(temp.name) / 'hub.sqlite'
        self.now = 1_800_000_000.0
        self.service = Service(self.path, simulator=True, clock=lambda: self.now)
        with self.service.connect() as db:
            db.executescript('''
                CREATE TABLE writes(op TEXT, kind TEXT);
                CREATE TRIGGER on_insert AFTER INSERT ON documents BEGIN
                    INSERT INTO writes VALUES ('insert', NEW.kind);
                END;
                CREATE TRIGGER on_update AFTER UPDATE ON documents BEGIN
                    INSERT INTO writes VALUES ('update', NEW.kind);
                END;
            ''')

    def take_writes(self):
        with self.service.connect() as db:
            rows = db.execute('SELECT op, kind FROM writes').fetchall()
            db.execute('DELETE FROM writes')
            return rows

    def test_hold_and_replay_leave_unchanged_documents_untouched(self):
        args = (ALICE, 'reserve_vehicle', {'vehicle_id': 'V1'}, 'first-hold')
        result = self.service.command(*args)
        self.assertCountEqual(self.take_writes(), [('insert', 'holds'), ('insert', 'audit')])

        with self.assertRaises(DomainError) as error:
            self.service.command(ALICE, 'reserve_vehicle', {'vehicle_id': 'V2'}, 'second-hold')
        self.assertEqual(error.exception.code, 'ACTIVE_JOURNEY')
        self.assertEqual(self.take_writes(), [])
        self.assertEqual(self.service.command(*args), result)
        self.assertEqual(self.take_writes(), [])

    def test_failed_command_persists_expiry_and_preserves_prior_audit(self):
        hold = self.service.command(ALICE, 'reserve_vehicle', {'vehicle_id': 'V1'}, 'hold')['record']
        original_audit = self.service.snapshot(OPERATOR)['audit'][0]
        self.take_writes()
        self.now = hold['expires_at']
        args = (ALICE, 'cancel_hold', {'hold_id': hold['id']}, 'late-cancellation')
        with self.assertRaises(DomainError) as first:
            self.service.command(*args)
        self.assertCountEqual(self.take_writes(), [('update', 'holds'), ('insert', 'audit')])

        reopened = Service(self.path, simulator=True, clock=lambda: self.now)
        with self.assertRaises(DomainError) as replay:
            reopened.command(*args)
        self.assertEqual(replay.exception.code, first.exception.code)
        state = reopened.snapshot(OPERATOR)
        self.assertEqual(state['revision'], 2)
        self.assertEqual(state['holds'][0]['status'], 'EXPIRED')
        self.assertIn(original_audit, state['audit'])
        self.assertCountEqual([entry['action'] for entry in state['audit']], ['reserve_vehicle', 'timers'])
        self.assertEqual(self.take_writes(), [])
