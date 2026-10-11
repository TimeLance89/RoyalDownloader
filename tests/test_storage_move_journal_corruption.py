"""Unknown move state must never be overwritten with an empty journal."""
import pytest
from storage import storage_move as legacy
from storage import storage_move_runtime as runtime


@pytest.mark.parametrize('payload', [
    b'{partial', b'[]', b'{}', b'{"jobs":"broken","history":[]}',
    b'{"jobs":[null],"history":[]}',
])
@pytest.mark.parametrize('writer', ['legacy', 'runtime'])
def test_corrupted_journal_is_preserved_before_another_save(tmp_path, monkeypatch, payload, writer):
    path = tmp_path / 'storage_move_jobs.json'
    path.write_bytes(payload)
    if writer == 'legacy':
        monkeypatch.setattr(legacy, '_MOVE_JOB_PATH', path)
        save = legacy._atomic_save_move_jobs_locked
    else:
        monkeypatch.setattr(runtime, 'JOB_PATH', path)
        save = runtime._save_locked
    with pytest.raises(OSError, match='Journal'):
        save()
    assert path.read_bytes() == payload
    assert not list(tmp_path.glob('.*.tmp'))


def test_new_move_is_rejected_before_planning_when_journal_is_corrupt(tmp_path, monkeypatch):
    path = tmp_path / 'storage_move_jobs.json'
    path.write_bytes(b'{partial')
    monkeypatch.setattr(runtime, 'JOB_PATH', path)
    monkeypatch.setattr(runtime, 'plan_move_candidate',
                        lambda *_args, **_kwargs: pytest.fail('must preserve unknown move state before planning'))
    with pytest.raises(OSError, match='Journal'):
        runtime.create_move_job({}, [], root_key='movies', relative_path='fixture.mp4',
                                token='fixture', expected_size=1, expires_at=1, destination_root='archive')
    assert path.read_bytes() == b'{partial'


@pytest.mark.parametrize('writer', ['legacy', 'runtime'])
def test_move_journal_symlink_is_not_followed(tmp_path, monkeypatch, writer):
    target = tmp_path / 'outside.json'
    target.write_bytes(b'{"jobs":[],"history":[]}')
    path = tmp_path / 'storage_move_jobs.json'
    path.symlink_to(target)
    if writer == 'legacy':
        monkeypatch.setattr(legacy, '_MOVE_JOB_PATH', path)
        save = legacy._atomic_save_move_jobs_locked
    else:
        monkeypatch.setattr(runtime, 'JOB_PATH', path)
        save = runtime._save_locked
    with pytest.raises(OSError, match='Journal'):
        save()
    assert path.is_symlink()
    assert target.read_bytes() == b'{"jobs":[],"history":[]}'
