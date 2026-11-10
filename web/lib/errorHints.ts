// One plain sentence for an algorithm / sandbox error: what went wrong and the
// usual cause. Pure pattern matching on the raw message — instant, no AI call.
// The raw message is still shown (folded) next to it.

export type ErrorHint = { summary: string; type: string; last: string };

/** The exception line of a Python traceback ("ValueError: …"), else the first line. */
function lastLine(raw: string): string {
  const lines = raw.split('\n').map((l) => l.trim()).filter(Boolean);
  const exc = [...lines].reverse().find((l) => /^[A-Za-z_.]*(Error|Exception|Warning|Exit|Interrupt)\b.*:/.test(l));
  return (exc ?? lines[0] ?? '').replace(/\s*Traceback \(most recent call last\):.*$/, '');
}

const q = (s?: string) => (s ? `「${s}」` : '');

type Rule = { re: RegExp; say: (m: RegExpMatchArray) => string };

const RULES: Rule[] = [
  // a parameter that should be a table got something else (usually a dataset name / id)
  { re: /(\w+) must be a (?:pandas )?DataFrame/i,
    say: (m) => `参数${q(m[1])}需要一张数据表，但调用时传进去的不是表（多半是数据集的名称或编号），所以算法没法运行。需要两份数据的算法，要在调用时把第二份数据也选上。` },
  { re: /expected (?:a )?(?:pandas )?DataFrame|not a DataFrame|DataFrame constructor not properly called/i,
    say: () => '算法需要一张数据表作为输入，但收到的不是表，所以没法运行。通常是没有选数据，或选中的数据已被清理。' },
  // missing column
  { re: /KeyError: ['"]([^'"]+)['"]/,
    say: (m) => `数据里没有列${q(m[1])}：可能是列名写错了，或者上一步的结果里已经没有这一列。` },
  { re: /(?:column|列)\s*['"「]?([^'"」\s]+)['"」]?\s*(?:not found|does not exist|不存在)/i,
    say: (m) => `数据里没有列${q(m[1])}：可能是列名写错了，或者上一步的结果里已经没有这一列。` },
  { re: /\[?['"]?([^\]'"]+)['"]?\]? not in index/i,
    say: (m) => `数据里没有列${q(m[1])}：可能是列名写错了，或者上一步的结果里已经没有这一列。` },
  { re: /unknown name ['"]([^'"]+)['"] — not a column/i,
    say: (m) => `表达式里的${q(m[1])}不是这份数据里的列名：检查拼写，或者先确认上一步的结果里有这一列。` },
  { re: /name must be a valid identifier/i,
    say: () => '新列的名称不合规：只能用字母、数字和下划线，不能以数字开头，也不能有空格或运算符（例如用 L_D，不要用 L/D）。' },
  { re: /unsupported (?:expression element|operator|comparison|constant)|keyword arguments are not supported/i,
    say: () => '表达式里用了不支持的写法：只支持列名、数字、四则运算、比较和常用数学函数。' },
  // text in numeric columns
  { re: /could not convert string to float: ?['"]?([^'"]*)['"]?/i,
    say: (m) => `有一列里混有文字${m[1] ? `（例如${q(m[1])}）` : ''}，不能当数字计算。可以先清洗数据，或换一列。` },
  { re: /unsupported operand type\(s\)|can't multiply sequence|must be real number, not str/i,
    say: () => '参与计算的列里有文字或空值，不能直接做数学运算。可以先清洗数据，或换一列。' },
  // NaN / empty
  { re: /Input (?:X )?contains NaN|contains NaN|NaN values/i,
    say: () => '数据里有缺失值（空格子），这个算法不接受。可以先用「缺失值填充」处理，再运行。' },
  { re: /empty DataFrame|is empty|zero-size array|0 sample\(s\)|no data/i,
    say: () => '输入的数据是空的，没有可以计算的行。通常是前一步的筛选条件把所有行都去掉了。' },
  { re: /Found array with \d+ sample\(s\)|n_samples=\d+ should be >=|Expected n_neighbors <= n_samples|fewer than|not enough/i,
    say: () => '数据行数太少，不够这个算法计算。可以放宽前面的筛选条件，或换一份更大的数据。' },
  // shape mismatches
  { re: /Length of values|length mismatch|operands could not be broadcast|shapes? .* (?:not aligned|mismatch)|must have the same length/i,
    say: () => '几列数据的长度对不上，没法逐行一起计算。通常是把两份行数不同的数据放在一起算了。' },
  // division / math
  { re: /ZeroDivisionError|division by zero/i,
    say: () => '计算中出现了除以零：某一列（或参数）里有 0，正好用作了除数。' },
  { re: /math domain error|invalid value encountered/i,
    say: () => '计算超出了数学定义的范围，比如对负数开方、对 0 取对数。检查数据里有没有负值或零。' },
  // parameters
  { re: /missing (?:\d+ )?required (?:positional |keyword )?argument:? ['"]?(\w+)/i,
    say: (m) => `缺少必填参数${q(m[1])}，算法没法开始计算。` },
  { re: /unexpected keyword argument ['"]?(\w+)/i,
    say: (m) => `传入了算法不认识的参数${q(m[1])}：可能参数名写错了，或这个算法的版本里没有这个参数。` },
  { re: /window_length must be (?:odd|less than|<=)|polyorder must be less than/i,
    say: () => '平滑窗口的参数不合适：窗口长度要是奇数、比阶数大，并且不能超过数据行数。' },
  // sandbox limits
  { re: /timed? ?out|TimeoutError|超时/i,
    say: () => '运行超时：数据量太大或计算太重，超过了沙箱允许的时间。可以先抽样或缩小范围再试。' },
  { re: /MemoryError|out of memory|Unable to allocate/i,
    say: () => '内存不够：这次计算需要的内存超过了沙箱的限制。可以先抽样或减少列数再试。' },
  { re: /No module named ['"]?([\w.]+)|import of ['"]?([\w.]+)['"]? is not allowed|forbidden (?:import|module)/i,
    say: (m) => `算法用了平台不允许或没有安装的库${q(m[1] || m[2])}。平台只支持 numpy、pandas、scipy、scikit-learn 和标准库。` },
  { re: /validation failed/i,
    say: () => '代码没有通过平台的安全检查（例如读写文件、联网或用了不允许的库），没有运行。' },
  { re: /dataset file is no longer available|数据已清理|FileNotFoundError/i,
    say: () => '要用的数据文件已经不在了（中间结果到期被清理）。可以在数据页对它「重跑」后再用。' },
];

export function explainErrorText(raw: string): ErrorHint {
  const text = String(raw ?? '');
  const last = lastLine(text);
  const type = (last.match(/^([A-Za-z_.]*(?:Error|Exception))/)?.[1] ?? '').split('.').pop() ?? '';
  // The algorithm already explained itself in Chinese (generated code is asked to) — use that.
  const own = last.replace(/^[A-Za-z_.]*(?:Error|Exception):\s*/, '').trim();
  if (/[一-鿿]/.test(own) && own.length <= 160) return { summary: own.endsWith('。') ? own : own + '。', type, last };
  for (const r of RULES) {
    const m = text.match(r.re);
    if (m) return { summary: r.say(m), type, last };
  }
  const generic: Record<string, string> = {
    ValueError: '算法收到的数据或参数取值不符合它的要求，没有算完。',
    TypeError: '算法收到的参数类型不对（比如该填数字的地方填了文字），没有算完。',
    IndexError: '算法按位置取数时超出了数据范围，通常是数据行数比预期少。',
    AttributeError: '算法代码里用了数据上不存在的属性或方法，多半是算法本身的问题，可以在编辑器里修。',
    NameError: '算法代码里用了未定义的名称，是算法本身的问题，可以在编辑器里修。',
    AssertionError: '算法自己的检查没有通过：输入的数据不满足它的前提条件。',
  };
  return { summary: generic[type] ?? '算法运行出错，没有算完。展开下面的原始报错可以看到具体原因。', type, last };
}
