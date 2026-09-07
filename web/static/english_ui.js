(() => {
  'use strict';

  const replacements = new Map([
    ['মার্কেট নির্বাচন করুন', 'Select a market'],
    ['মার্কেট নির্বাচন করলে সংশ্লিষ্ট নিউজ দেখা যাবে।', 'Select a market to view related news.'],
    ['এখনও কোনো মার্কেট নির্বাচন করা হয়নি।', 'No market selected yet.'],
    ['একটি মার্কেট নির্বাচন করে GET SIGNAL চাপুন।', 'Select a market and click GET SIGNAL.'],
    ['রিফ্রেশ', 'REFRESH'],
    ['বর্তমান সেশন', 'Current Session'],
    ['মার্কেট অ্যাক্টিভিটি', 'Market Activity'],
    ['সেরা ট্রেডিং উইন্ডো', 'Best Trading Window'],
    ['নিউজ রিস্ক', 'News Risk'],
    ['পরবর্তী নিউজ', 'Next News'],
    ['এটি session + scheduled-news risk ভিত্তিক নির্দেশনা। এটি BUY/SELL-এর গ্যারান্টি নয়।', 'Session + scheduled-news risk guidance. This is not a BUY/SELL guarantee.'],
    ['আসন্ন নিউজ — Pre-News Direction', 'Upcoming News — Pre-News Direction'],
    ['সব মার্কেটের মধ্যে সবচেয়ে কাছের আসন্ন নিউজের Market, সময়, Direction ও Percentage এখানে দেখানো হবে।', 'The nearest upcoming news across configured markets, its market, time, direction and percentage are shown here.'],
    ['আসন্ন নিউজ পাওয়া যাচ্ছে না।', 'No upcoming news is available.'],
    ['Pre-News Direction এখন পাওয়া যাচ্ছে না।', 'Pre-News Direction is currently unavailable.'],
    ['মার্কেট', 'Market'],
    ['নিউজ সময়', 'News Time'],
    ['Percentage', 'Percentage'],
    ['দিক এখনো নিশ্চিত নয়', 'Direction not confirmed'],
    ['দিক নিশ্চিত নয়', 'Direction not confirmed'],
    ['নিশ্চিত নয়', 'Not confirmed'],
    ['উপরে', 'UP'],
    ['নিচে', 'DOWN'],
    ['নিকটতম নিউজ', 'NEAREST NEWS'],
    ['পরের নিউজগুলো — অল্প সময় বাকি থাকা আগে:', 'Upcoming News — nearest first:'],
    ['সবচেয়ে কাছের', 'Nearest'],
    ['পরবর্তী', 'Next'],
    ['মোট ', 'Total '],
    ['টি আসন্ন নিউজ • সবগুলো সময় অনুযায়ী সাজানো।', ' upcoming news event(s) • sorted by time.'],
    ['সময় পার হয়েছে', 'Event time reached'],
    ['আর ', 'In '],
    ['ঘণ্টা', 'h'],
    ['মিনিট', 'm'],
    ['সেকেন্ড', 's'],
    ['বাংলাদেশ সময়', 'Bangladesh Time'],
    ['নির্ধারিত নিউজ', 'Scheduled News'],
    ['নিউজ রিস্ক', 'News Risk'],
    ['উচ্চ', 'HIGH'],
    ['মাঝারি', 'MEDIUM'],
    ['কম', 'LOW'],
    ['অপেক্ষা করা ভালো', 'WAIT'],
    ['শক্ত সেটআপের অপেক্ষা', 'WAIT — Strong setup required'],
    ['ট্রেডিং উইন্ডো সক্রিয় — সেটআপ মিললে ট্রেড', 'TRADE WINDOW — Trade only when setup confirms'],
    ['এখন ট্রেড এড়িয়ে চলো', 'AVOID — Do not trade before the news release'],
    ['নিউজ রিলিজের আগে ট্রেড নয়', 'AVOID — No trade before the news release'],
    ['নিউজের আগে entry নয়', 'No entry before the news'],
    ['দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন', 'Separate direction analysis required'],
    ['দিকের জন্য আলাদা বিশ্লেষণ প্রয়োজন', 'Separate direction analysis required'],
    ['News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।', 'Alpha Vantage was not called to display News Events.'],
    ['News Events দেখানোর জন্য Alpha Vantage কল করা হয়নি।', 'Alpha Vantage was not called to display News Events.'],
    ['Direction ও confidence Alpha Vantage news sentiment-এর strength থেকে হিসাব করা PRE-NEWS সম্ভাব্য bias; actual news result/price reaction বদলে দিতে পারে। নিউজের সময়/impact economic calendar থেকে আসে।', 'Direction and confidence are a PRE-NEWS bias derived from Alpha Vantage news sentiment strength; the actual result or price reaction can change it. News time and impact come from the economic calendar.'],
    ['Direction বিশ্লেষণ শুধু high-impact নিউজের ৫ মিনিটের window-তে করা হবে।', 'Direction analysis is performed only within the 5-minute window around high-impact news.'],
    ['Alpha Vantage সাময়িকভাবে পাওয়া যায়নি; direction নিশ্চিত নয়।', 'Alpha Vantage is temporarily unavailable; direction is not confirmed.'],
    ['Alpha Vantage সাময়িকভাবে পাওয়া যায়নি; direction নিশ্চিত নয়।', 'Alpha Vantage is temporarily unavailable; direction is not confirmed.'],
    ['নিউজের currency নির্বাচিত pair-এর সঙ্গে সরাসরি মেলে না।', 'News currency does not directly match the selected pair.'],
    ['এই নিউজের sentiment নির্বাচিত pair-এর মুদ্রার সঙ্গে সরাসরি মেলে না।', 'This news sentiment does not directly match the selected pair currency.'],
    ['পর্যাপ্ত bullish/bearish sentiment নেই; নিউজের actual result না আসা পর্যন্ত দিক নিশ্চিত নয়।', 'Insufficient bullish/bearish sentiment; direction is not confirmed until the actual news result.'],
    ['ইতিবাচক', 'Positive'],
    ['নেতিবাচক', 'Negative'],
    ['নিরপেক্ষ', 'Neutral'],
    ['সেশন ট্রানজিশন', 'Session Transition'],
    ['লন্ডন + নিউ ইয়র্ক ওভারল্যাপ', 'London + New York Overlap'],
    ['লন্ডন সেশন', 'London Session'],
    ['নিউ ইয়র্ক সেশন', 'New York Session'],
    ['এশিয়া সেশন', 'Asia Session'],
    ['সেরা উইন্ডো:', 'Best window:'],
    ['ভালো উইন্ডো:', 'Good window:'],
    ['মুভমেন্ট তুলনামূলক কম হতে পারে', 'Movement may be relatively lower'],
    ['বড় সেটআপ না হলে অপেক্ষা করা ভালো', 'Wait unless a strong setup appears'],
    ['মোট', 'Total'],
    ['জয়', 'WIN'],
    ['হার', 'LOSS'],
    ['জয়ের হার', 'Win Rate'],
    ['গত ২৪ ঘণ্টার ফলাফল', 'Last 24 Hours Performance'],
    ['গত ২৪ ঘণ্টার ফলাফল — শুধু কেনা ও বিক্রি', 'Last 24 Hours — BUY/SELL only'],
    ['কেনা', 'BUY'],
    ['বিক্রি', 'SELL'],
    ['ক্রিপ্টো বাজার', 'CRYPTO MARKET'],
    ['বাস্তব বাজার', 'REAL MARKET'],
    ['Performance দেখতে খুলুন।', 'Open to view performance.'],
    ['কোনো কাছের high-impact নিউজ নেই', 'No nearby high-impact news'],
    ['High-impact নিউজ', 'High-impact news'],
    ['গুরুত্বপূর্ণ নিউজ', 'Important news'],
    ['পরবর্তী নিউজ', 'Next news'],
    ['নিউজের আগে', 'Before news'],
    ['অবৈধ মার্কেট।', 'Invalid market.'],
    ['প্রথমে একটি মার্কেট নির্বাচন করুন।', 'Select a market first.'],
  ]);

  const normalizeText = (text) => {
    let out = String(text ?? '');
    replacements.forEach((value, key) => { out = out.split(key).join(value); });
    return out;
  };

  function translate(root = document.body) {
    if (!root) return;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    nodes.forEach(node => {
      if (!node.nodeValue || !node.nodeValue.trim()) return;
      const next = normalizeText(node.nodeValue);
      if (next !== node.nodeValue) node.nodeValue = next;
    });
    root.querySelectorAll?.('[aria-label],[title],[placeholder]').forEach(el => {
      ['aria-label','title','placeholder'].forEach(attr => {
        const value = el.getAttribute(attr);
        if (value) el.setAttribute(attr, normalizeText(value));
      });
    });
  }

  let timer = null;
  const schedule = () => {
    clearTimeout(timer);
    timer = setTimeout(() => translate(document.body), 40);
  };

  translate(document.body);
  if ('MutationObserver' in window) {
    new MutationObserver(schedule).observe(document.body, {childList:true, subtree:true, characterData:true});
  }
})();
