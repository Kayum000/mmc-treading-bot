# MMC Floating Signal — Desktop Setup

এই extensionটি Quotex Web App-এর desktop Chrome/Edge-এ MMC floating signal button দেখানোর জন্য।

## Install

1. এই repository থেকে `browser_extension` folder download করুন।
2. ZIP হলে আগে Extract করুন।
3. Chrome/Edge-এ Extensions খুলুন।
4. **Developer mode** ON করুন।
5. **Load unpacked** চাপুন।
6. Extract করা `browser_extension` folder নির্বাচন করুন।
7. Quotex Web App সম্পূর্ণ reload করুন (প্রয়োজনে tab বন্ধ করে আবার খুলুন)।

## ব্যবহার

- Quotex-এ যে Real Market বা OTC market বর্তমানে খোলা আছে, extension সেটি page থেকে detect করবে।
- **SCAN** চাপলে সেই market-এর signal + score দেখাবে।
- **Floating Auto** ON করলে auto scan/entry timing চালু হবে।
- Floating Auto ON থাকলে page-এর existing auto-toggle থাকলে সেটি বন্ধ করার চেষ্টা করা হবে, যাতে একসাথে একাধিক auto signal system না চলে।

> Browser extension সাধারণত Chrome Web Store ছাড়া সরাসরি one-click install হয় না; Load unpacked পদ্ধতিতে একবার সেটআপ করতে হয়।