import { test } from 'node:test';
import assert from 'node:assert/strict';
import { balanceMicro, cnyBalance, codeBudget, formatCnyBalance, money, moneyMicro } from '../src/api/code-values.ts';

test('V2 amounts preserve exact micro-CNY beyond Number precision', () => {
  assert.equal(moneyMicro('9007199254740991.000001'), 9007199254740991000001n);
  assert.equal(moneyMicro('0.1'), 100000n);
  assert.equal(balanceMicro('-0.000001'), -1n);
  assert.equal(formatCnyBalance(-1n), '-0.000001');
  assert.equal(formatCnyBalance(0n), '0.000000');
  assert.equal(formatCnyBalance(9007199254740991000001n), '9007199254740991.000001');
});

test('V2 Money and CnyBalance remain separate strict contracts', () => {
  for (const value of [null, undefined, true, 1, 1.5, '', '-0', '-1', '+1', '1e2', '01', '.1', '1.', '1.0000001', ' 1', '1\n', '１']) {
    assert.throws(() => money(value), TypeError, String(value));
  }
  for (const value of ['-0.000000', '+0.000001', '1', '01.000000', '1e-6', '1.000000\n']) {
    assert.throws(() => cnyBalance(value), TypeError, value);
  }
  assert.equal(cnyBalance('-0.000001'), '-0.000001');
  assert.throws(() => money('-0.000001'), TypeError);
});

test('Coding/Testing budget validates one exact snapshot without hiding overrun', () => {
  const budget = {
    limit_cny: '1.000000', settled_cny: '1.000000',
    reserved_cny: '0.000001', available_cny: '-0.000001', unresolved_call_count: 1,
  };
  assert.deepEqual(codeBudget(budget), budget);
  assert.ok(Object.isFrozen(codeBudget(budget)));
  for (const replacement of [
    { available_cny: '0.000000' }, { settled_cny: null },
    { unresolved_call_count: -1 }, { reserved_cny: '-0.000001' }, { extra: 1 },
  ]) {
    assert.throws(() => codeBudget({ ...budget, ...replacement }), TypeError);
  }
  const { available_cny, ...missing } = budget;
  assert.throws(() => codeBudget(missing), TypeError);
  assert.equal(available_cny, '-0.000001');
});
