from app.core.config_diff import diff_policies, diff_policy_set, render_markdown
from app.core.security import SECURITY
from app.schemas import Policy, PolicySet


def _p(pid, **kw):
    return Policy(id=pid, type=kw.pop('type', 'qos'), name=kw.pop('name', pid),
                  action=kw.pop('action', 'permit'), **kw)


def test_identical_sets_have_no_items():
    d = diff_policies([_p('a'), _p('b')], [_p('a'), _p('b')])
    assert d['items'] == []
    assert d['summary'] == {'added': 0, 'removed': 0, 'modified': 0,
                            'unchanged': 2, 'requires_approval': False}


def test_add_remove_modify_are_separated():
    d = diff_policies(
        [_p('keep'), _p('gone'), _p('edit', priority=100)],
        [_p('keep'), _p('new'), _p('edit', priority=200)],
    )
    assert [p.id for p in d['added']] == ['new']
    assert [p.id for p in d['removed']] == ['gone']
    assert [c['policy'].id for c in d['changed']] == ['edit']
    assert d['changed'][0]['fields'] == {'priority': {'from': 100, 'to': 200}}
    assert d['summary']['unchanged'] == 1


def test_high_risk_sorted_first_and_requires_approval():
    # 命令形态对齐 SecurityChecker.dangerous_ops 的真实正则（^ip\s+route\s+del\b）
    risky = _p('z-danger', type='route', action='delete',
               commands=['ip route del 10.0.0.0/8'])
    d = diff_policies([], [_p('a-plain'), risky], is_dangerous=SECURITY._is_dangerous)
    assert d['items'][0]['policy'].id == 'z-danger', '危险项必须排最前'
    assert d['items'][0]['risk'] == 'high'
    assert d['summary']['requires_approval'] is True


def test_no_danger_predicate_means_no_guessed_risk():
    d = diff_policies([], [_p('x', type='route', action='delete',
                              commands=['ip route del 10.0.0.0/8'])])
    assert all(i['risk'] == 'low' for i in d['items'])
    assert d['summary']['requires_approval'] is False


def test_diff_is_pure_does_not_mutate_inputs():
    before = _p('a', priority=100)
    after = _p('a', priority=300)
    diff_policies([before], [after])
    assert before.priority == 100 and after.priority == 300


def test_diff_policy_set_accepts_policy_set():
    ps = PolicySet(intent_id='i1', policies=[_p('x'), _p('y')])
    d = diff_policy_set([_p('x')], ps)
    assert d['summary'] == {'added': 1, 'removed': 0, 'modified': 0,
                            'unchanged': 1, 'requires_approval': False}


def test_markdown_reports_approval_and_commands():
    d = diff_policies([], [_p('r1', type='route', action='delete',
                              commands=['ip link set eth0 down'],
                              rollback_commands=['ip link set eth0 up'])],
                      is_dangerous=SECURITY._is_dangerous)
    md = render_markdown(d)
    assert '必须走审批流' in md
    assert '`ip link set eth0 down`' in md
    assert '`ip link set eth0 up`' in md


def test_markdown_empty_is_still_valid_artifact():
    md = render_markdown(diff_policies([_p('a')], [_p('a')]))
    assert '无变更' in md
    assert md.startswith('# 变更提案')
