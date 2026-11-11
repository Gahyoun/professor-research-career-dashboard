"""Korean personal name -> romanization variants and a strict matcher for OpenAlex raw author names."""
import re, itertools
SURNAME = {'김':['kim','gim'],'이':['lee','yi','rhee','rhie','li','ri','ree'],'박':['park','pak','bak'],'최':['choi','choe','chey'],
 '정':['jung','jeong','chung','joung','cheong'],'강':['kang','gang'],'조':['cho','jo','joh','zo'],'윤':['yoon','yun'],'장':['jang','chang'],
 '임':['lim','im','rim','yim'],'한':['han'],'오':['oh','o'],'서':['seo','suh','so'],'신':['shin','sin'],'권':['kwon','gwon'],'황':['hwang'],
 '안':['ahn','an'],'송':['song'],'전':['jeon','jun','chun','cheon'],'홍':['hong'],'유':['yoo','yu','you','ryu'],'류':['ryu','yoo','yu','ryoo','lyu'],
 '고':['ko','go','koh'],'문':['moon','mun'],'양':['yang'],'손':['son','sohn'],'배':['bae','pae'],'백':['baek','paik','paek','baik','back'],
 '허':['heo','huh','hur'],'남':['nam'],'심':['shim','sim'],'노':['noh','no','roh','rho'],'하':['ha'],'곽':['kwak','gwak'],'성':['sung','seong'],
 '차':['cha'],'주':['joo','ju','chu'],'우':['woo','u'],'구':['koo','ku','gu'],'민':['min'],'진':['jin','chin'],'나':['na','ra'],'지':['ji','chi'],
 '엄':['eom','um','uhm'],'채':['chae'],'원':['won'],'천':['cheon','chun'],'방':['bang'],'공':['kong','gong'],'현':['hyun','hyeon'],'함':['ham'],
 '변':['byun','byeon'],'염':['yeom','yum'],'여':['yeo','yuh'],'추':['choo','chu'],'도':['do','doh'],'소':['so'],'석':['seok','suk'],
 '선':['sun','seon'],'설':['seol','sul'],'마':['ma'],'길':['gil','kil'],'연':['yeon','yun'],'위':['wi','wee'],'표':['pyo'],'명':['myung','myeong'],
 '기':['ki','gi'],'반':['ban','bahn'],'왕':['wang'],'금':['keum','geum'],'옥':['ok'],'육':['yook','yuk'],'인':['in'],'맹':['maeng'],'제':['je'],
 '모':['mo'],'탁':['tak'],'국':['kook','guk'],'어':['eo','uh'],'은':['eun'],'편':['pyun','pyeon'],'용':['yong'],'예':['ye'],'경':['kyung','gyeong'],
 '봉':['bong'],'사':['sa'],'부':['boo','bu'],'황보':['hwangbo'],'남궁':['namgung','namkung'],'선우':['sunwoo','seonwoo','seonu'],'제갈':['jegal'],'독고':['dokgo']}
INI = ['g','kk','n','d','tt','r','m','b','pp','s','ss','','j','jj','ch','k','t','p','h']
INI_ALT = {'g':['g','k'],'d':['d','t'],'b':['b','p'],'j':['j','ch'],'r':['r','l'],'s':['s','sh'],'':['']}
VOW = ['a','ae','ya','yae','eo','e','yeo','ye','o','wa','wae','oe','yo','u','wo','we','wi','yu','eu','ui','i']
VOW_ALT = {'eo':['eo','u','o'],'yeo':['yeo','yu','yo'],'eu':['eu','u'],'u':['u','oo'],'ui':['ui','ee','i'],'i':['i','ee'],
           'oe':['oe','oi'],'wo':['wo','o'],'ae':['ae','e'],'o':['o','oh']}
FIN = ['','k','k','k','n','n','n','t','l','k','m','l','l','l','p','l','m','p','p','t','t','ng','t','t','k','t','p','t']
FIN_ALT = {'k':['k','g'],'t':['t','d'],'p':['p','b'],'l':['l','r'],'ng':['ng'],'n':['n'],'m':['m'],'':['']}
def syll(ch):
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172: return [ch]
    i, v, f = c // 588, (c % 588) // 28, c % 28
    ini = INI[i]; vow = VOW[v]; fin = FIN[f]
    if ini == '' and ch in '이': pass
    out = set()
    for a in INI_ALT.get(ini, [ini]):
        for b in VOW_ALT.get(vow, [vow]):
            for z in FIN_ALT.get(fin, [fin]):
                out.add(a + b + z)
    # common fixed forms
    fixed = {'희':['hee','hui'],'혁':['hyuk','hyeok'],'현':['hyun','hyeon'],'형':['hyung','hyeong'],'영':['young','yeong','yung'],
             '연':['yeon','yun','yon'],'용':['yong','ryong'],'준':['jun','joon','chun'],'중':['jung','joong'],'정':['jung','jeong','chung','joung'],
             '성':['sung','seong'],'석':['seok','suk','sok'],'철':['chul','cheol'],'천':['chun','cheon'],'선':['sun','seon','son'],
             '섭':['sub','seop','sup'],'순':['soon','sun'],'수':['soo','su'],'우':['woo','u','wu'],'주':['joo','ju','chu'],'구':['koo','ku','gu'],
             '규':['kyu','gyu'],'경':['kyung','kyeong','gyeong','kyong'],'기':['ki','gi'],'근':['keun','geun','kun'],'두':['doo','du'],
             '덕':['duk','deok','dok'],'훈':['hoon','hun'],'윤':['yoon','yun'],'은':['eun'],'원':['won'],'운':['woon','un'],'욱':['wook','uk'],
             '범':['bum','beom','pom'],'병':['byung','byeong','pyung'],'봉':['bong'],'철':['chul','cheol'],'충':['choong','chung'],
             '태':['tae'],'택':['taek'],'대':['dae'],'재':['jae'],'채':['chae'],'세':['se'],'혜':['hye','hae'],'예':['ye'],'계':['kye','gye'],
             '래':['rae','lae'],'례':['rye','ye'],'려':['ryeo','ryu','ryo','lyeo'],'열':['yeol','yul'],'렬':['ryeol','ryul','yeol'],
             '률':['ryul','yul'],'룡':['ryong','yong'],'량':['ryang','yang'],'린':['rin','lin'],'리':['ri','lee','li'],'란':['ran','lan'],
             '라':['ra','la'],'로':['ro','lo'],'록':['rok','lok'],'숙':['sook','suk'],'식':['sik','shik'],'신':['shin','sin'],'시':['si','shi'],
             '심':['shim','sim'],'실':['sil','shil'],'승':['seung','sung'],'상':['sang'],'민':['min'],'진':['jin','chin'],'지':['ji','chi'],
             '찬':['chan'],'창':['chang'],'호':['ho'],'환':['hwan'],'화':['hwa'],'효':['hyo'],'휘':['hwi','hui'],'의':['eui','ui','ee'],
             '익':['ik','ick'],'일':['il'],'인':['in'],'임':['im','lim'],'자':['ja'],'제':['je'],'조':['jo','cho'],'종':['jong','chong'],
             '동':['dong','tong'],'도':['do'],'돈':['don'],'명':['myung','myeong'],'문':['moon','mun'],'미':['mi'],'남':['nam'],'나':['na'],
             '하':['ha'],'한':['han'],'해':['hae'],'학':['hak'],'향':['hyang'],'헌':['heon','hun'],'홍':['hong'],'국':['kook','guk','kuk'],
             '군':['kun','gun'],'권':['kwon','gwon'],'광':['kwang','gwang'],'관':['kwan','gwan'],'균':['kyun','gyun'],'금':['keum','geum'],
             '길':['gil','kil'],'건':['gun','geon','kun','keon'],'걸':['geol','kul','gul'],'곤':['gon','kon'],'공':['kong','gong'],'교':['kyo','gyo']}
    if ch in fixed: out |= set(fixed[ch])
    return sorted(out)
def rr(ch):
    c = ord(ch) - 0xAC00
    if not 0 <= c < 11172: return ch
    fixed = {'희':'hee','혁':'hyuk','현':'hyun','형':'hyung','영':'young','정':'jung','성':'sung','석':'seok','철':'chul','준':'jun',
             '수':'soo','우':'woo','주':'joo','구':'koo','규':'kyu','경':'kyung','기':'ki','훈':'hoon','윤':'yoon','범':'bum','병':'byung',
             '숙':'sook','식':'sik','신':'shin','승':'seung','근':'keun','중':'jung','종':'jong','동':'dong','순':'soon','선':'sun','연':'yeon'}
    if ch in fixed: return fixed[ch]
    i, v, f = c // 588, (c % 588) // 28, c % 28
    return INI[i] + VOW[v] + FIN[f]
def norm(s): return re.sub(r'[^a-z]', '', (s or '').lower())
def split_kor(name):
    name = name.strip()
    if len(name) >= 3 and name[:2] in ('황보','남궁','선우','제갈','독고'): return name[:2], name[2:]
    return name[:1], name[1:]
def variants(name, limit=6):
    """A few query forms: 'Given Surname' with given syllables joined and hyphen/space-separated (RR first)."""
    sur, giv = split_kor(name)
    s = SURNAME.get(sur, [norm(''.join(syll(c)[0] for c in sur))])[0]
    rr = [globals()['rr'](c) for c in giv]
    forms = [''.join(rr).capitalize() + ' ' + s.capitalize(), ' '.join(x.capitalize() for x in rr) + ' ' + s.capitalize()]
    return forms[:limit]
def matcher(name):
    """Regex on letters-only raw names, either order: surname variant + given syllables (each any variant).
    Initials-only given names are not accepted (too ambiguous for a name-only match)."""
    sur, giv = split_kor(name)
    S = '|'.join(SURNAME.get(sur, [norm(''.join(syll(c)[0] for c in sur))]))
    Gv = ''.join('(?:%s)' % '|'.join(syll(c)) for c in giv)
    return re.compile(r'^(?:(?:%s)(?:%s)|(?:%s)(?:%s))$' % (Gv, S, S, Gv))
def matches(name, raw):
    return bool(matcher(name).match(norm(raw)))
if __name__ == '__main__':
    for n, r, exp in [('이진호','Jinho Lee',1),('이진호','Jin-Ho Lee',1),('이진호','Lee Jinho',1),('이진호','J. Lee',0),('이미진','Mi Jin Lee',1),
                      ('이미진','Min Ji Lee',0),('김성훈','Sunghoon Kim',1),('김성훈','Sung-Hoon Kim',1),('정희','Hee Jung',1),('최정희','Jeong-Hui Choi',1),
                      ('박병규','Byung Kyu Park',1),('박병규','Byeong Gyu Park',1),('이상훈','Sangmin Lee',0)]:
        assert matches(n, r) == bool(exp), (n, r)
    print(variants('이진호'), 'ok')
