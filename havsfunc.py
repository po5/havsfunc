import vapoursynth as vs
import functools
import math

"""Holy's ported AviSynth functions for VapourSynth."""


# Suggested by Mystery Keeper in "Denoise of tv-anime" thread
def ediaa(a):
    core = vs.get_core()
    
    if not isinstance(a, vs.VideoNode) or a.format.bits_per_sample != 8:
        raise ValueError('ediaa: This is not a 8-bit clip !')
    
    return Resize(core.std.Transpose(core.eedi2.EEDI2(core.std.Transpose(core.eedi2.EEDI2(a, field=1)), field=1)), a.width, a.height, -0.5, -0.5)


# Anti-aliasing with contra-sharpening by Didée
def daa(c):
    core = vs.get_core()
    
    if not isinstance(c, vs.VideoNode):
        raise ValueError('daa: This is not a clip !')
    
    nn = core.nnedi3.nnedi3(c, field=3)
    dbl = core.std.Merge(core.std.SelectEvery(nn, 2, [0]), core.std.SelectEvery(nn, 2, [1]))
    dblD = core.std.MakeDiff(c, dbl)
    shrpD = core.std.MakeDiff(dbl, core.rgvs.RemoveGrain(dbl, 20 if c.width>1100 else 11))
    DD = core.rgvs.Repair(shrpD, dblD, 13)
    return core.std.MergeDiff(dbl, DD)


# Anti-aliasing with edge masking by martino, mask using "sobel" taken from Kintaro's useless filterscripts and modded by thetoof for spline36
#
# Parameters:
#  noring [bool] - In case of supersampling, indicates that a non-ringing algorithm must be used. Default is false
def maa(input, noring=False):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode) or input.format.id != vs.YUV420P8:
        raise ValueError('maa: This is not a YUV420P8 clip !')
    
    mask = core.generic.Inflate(core.generic.Sobel(core.std.ShufflePlanes(input, planes=[0], colorfamily=vs.GRAY), 40, 40))
    aa_clip = Resize(
      core.avs.SangNom(
        core.std.Transpose(
          core.avs.SangNom(
            core.std.Transpose(Resize(input, input.width*2, input.height*2, kernel='spline64' if noring else 'spline36', planes=[3, 1, 1], noring=noring))))),
      input.width, input.height, planes=[3, 1, 1])
    return core.std.MaskedMerge(input, aa_clip, mask, planes=[0])


# Developped in the "fine anime antialiasing thread"
#
# Parameters:
#  dark [int]       - Strokes darkening strength. Default is 38
#  thin [int]       - Presharpening. Default is 10
#  sharp [int]      - Postsharpening. Default is 150
#  smooth [int]     - Postsmoothing. Default is -1
#  stabilize [bool] - Use post stabilization with Motion Compensation. Default is false
#  tradius [int]    - 1: MDegrain1, 2: MDegrain2, 3: MDegrain3. Default is 2
#  aapel [int]      - Accuracy of the motion estimation. Default is 2
#  aaov [int]       - Block overlap value. Default is 8 for HD / 4 for SD
#  aablk [int]      - Size of a block. Default is 16 for HD / 8 for SD
#  aatype [string]  - Use SangNom() or EEDI2() for anti-aliasing. Default is 'SangNom'
#  noring [bool]    - In case of supersampling, indicates that a non-ringing algorithm must be used for aatype='SangNom'. Default is false
def SharpAAMCmod(orig, dark=38, thin=10, sharp=150, smooth=-1, stabilize=False, tradius=2, aapel=2, aaov=None, aablk=None, aatype='SangNom', noring=False):
    core = vs.get_core()
    
    if not isinstance(orig, vs.VideoNode) or orig.format.id != vs.YUV420P8:
        raise ValueError('SharpAAMCmod: This is not a YUV420P8 clip !')
    aatype = aatype.lower()
    if aatype not in ['sangnom', 'eedi2']:
        raise ValueError("SharpAAMCmod: Please use SangNom or EEDI2 for 'aatype'")
    
    w = orig.width
    h = orig.height
    if aaov is None:
        aaov = 8 if w > 1100 else 4
    if aablk is None:
        aablk = 16 if w > 1100 else 8
    
    # x 128 / 0.86 ^ 255 *
    def get_lut(x):
        return min(round((x / 128) ** 0.86 * 255), 255)
    
    orig_y = core.std.ShufflePlanes(orig, planes=[0], colorfamily=vs.GRAY)
    m = core.std.Lut(core.std.Expr([core.generic.Convolution(orig_y, [5, 10, 5, 0, 0, 0, -5, -10, -5], divisor=4, saturate=False),
                                    core.generic.Convolution(orig_y, [5, 0, -5, 10, 0, -10, 5, 0, -5], divisor=4, saturate=False)],
                                   ['x y max']),
                     function=get_lut)
    if thin == 0 and dark == 0:
        preaa = orig
    elif thin == 0:
        preaa = FastLineDarkenMOD(orig, strength=dark)
    elif dark == 0:
        preaa = core.avs.aWarpSharp2(orig, depth=thin)
    else:
        preaa = core.avs.aWarpSharp2(FastLineDarkenMOD(orig, strength=dark), depth=thin)
    if aatype == 'sangnom':
        aa = Resize(
          core.avs.SangNom(
            core.std.Transpose(core.avs.SangNom(core.std.Transpose(Resize(preaa, w*2, h*2, kernel='spline64' if noring else 'spline36', noring=noring))))),
          w, h)
    else:
        aa = ediaa(preaa)
    if sharp == 0 and smooth == 0:
        postsh = aa
    else:
        postsh = LSFmod(aa, strength=sharp, overshoot=1, soft=smooth)
    merged = core.std.MaskedMerge(orig, postsh, m)
    
    if stabilize:
        sD = core.std.MakeDiff(orig, merged)
        
        origsuper = core.mv.Super(orig, pel=aapel)
        sDsuper = core.mv.Super(sD, pel=aapel, levels=1)
        
        fv1 = core.mv.Analyse(origsuper, blksize=aablk, isb=False, delta=1, overlap=aaov)
        bv1 = core.mv.Analyse(origsuper, blksize=aablk, isb=True, delta=1, overlap=aaov)
        if tradius > 1:
            fv2 = core.mv.Analyse(origsuper, blksize=aablk, isb=False, delta=2, overlap=aaov)
            bv2 = core.mv.Analyse(origsuper, blksize=aablk, isb=True, delta=2, overlap=aaov)
        if tradius > 2:
            fv3 = core.mv.Analyse(origsuper, blksize=aablk, isb=False, delta=3, overlap=aaov)
            bv3 = core.mv.Analyse(origsuper, blksize=aablk, isb=True, delta=3, overlap=aaov)
        if tradius <= 1:
            sDD = core.mv.Degrain1(sD, sDsuper, bv1, fv1)
        elif tradius == 2:
            sDD = core.mv.Degrain2(sD, sDsuper, bv1, fv1, bv2, fv2)
        else:
            sDD = core.mv.Degrain3(sD, sDsuper, bv1, fv1, bv2, fv2, bv3, fv3)
        
        reduc = 0.4
        sDD = core.std.Merge(core.std.Expr([sD, sDD], ['x 128 - abs y 128 - abs < x y ?']), sDD, weight=[1-reduc])
        
        return core.std.MakeDiff(orig, sDD)
    else:
        return merged


# Changes 2008-08-18: (Didée)
# - Replaced the ugly stackXXX cascade with mt_LutSpa() (requires MaskTools v2.0a35)
# - Changed Quant and Offset defaults to 24,28,2,4,4,8
#
# Changes 2010-05-25:
# - Explicitly specified parameters of mt_LutSpa()
#   (required due to position of new 'biased' parameter, starting from MaskTools 2.0a43)
# - Non mod 16 input is now padded with borders internally
#
# Changes 2010-08-18:
# - Replaced AddBorders with PointResize
# - Changed Quant and Offset defaults to 18,19,3,4,1,1 to reduce blurring
#
# Changes 2010-10-16:
# - Replaced 'relative' with the new 'mode' parameter in mt_LutSpa(), starting from MaskTools 2.0a45
# - Changed Quant and Offset defaults to 24,26,1,1,2,2 to increase effectiveness, but still within sensible limits.
#   (see for details: http://forum.doom9.org/showthread.php?p=810932#post810932)
#
# Changes 2011-11-29: (06_taro)
# - Replaced (chroma=uv>2?"process":"ignore") by (chroma=uv>2?"process":"copy") to avoid garbage clip when uv=2.
#   The formal parameter is not used by MaskTools2 any more, if ever used.
#   Foxyshadis once mentioned chroma="ignore" but I had never found a document containing it.
#
# Parameters:
#  quant1 [int] - Strength of block edge deblocking. Default is 24
#  quant2 [int] - Strength of block internal deblocking. Default is 26
#  aOff1 [int]  - Halfway "sensitivity" and halfway a strength modifier for borders. Default is 1
#  aOff2 [int]  - Halfway "sensitivity" and halfway a strength modifier for block interiors. Default is 1
#  bOff1 [int]  - "sensitivity to detect blocking" for borders. Default is 2
#  bOff2 [int]  - "sensitivity to detect blocking" for block interiors. Default is 2
#  uv [int]     - 3: use proposed method for chroma deblocking, 2: no chroma deblocking at all(fastest method), 1|-1: directly use chroma debl. from the normal|strong Deblock(). Default is 3
def Deblock_QED(clp, quant1=24, quant2=26, aOff1=1, bOff1=2, aOff2=1, bOff2=2, uv=3):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode):
        raise ValueError('Deblock_QED: This is not a clip !')
    
    median = 1 << (clp.format.bits_per_sample - 1)
    peak = (1 << clp.format.bits_per_sample) - 1
    
    if clp.format.num_planes == 1:
        uv = 2
    planes = [0, 1, 2] if uv == 3 else [0]
    
    # add borders if clp is not mod 8
    w = clp.width
    h = clp.height
    padX = 8 - w % 8 if w & 7 else 0
    padY = 8 - h % 8 if h & 7 else 0
    clp = Resize(clp, w+padX, h+padY, 0, 0, w+padX, h+padY, kernel='point')
    
    # block
    block = core.std.BlankClip(clp, width=6, height=6, format=vs.GRAY8, length=1, color=[0])
    block = core.std.AddBorders(block, 1, 1, 1, 1, color=[255])
    horizontal = []
    vertical = []
    for i in range(int(clp.width / 8)):
        horizontal += [block]
    block = core.std.StackHorizontal(horizontal)
    for i in range(int(clp.height / 8)):
        vertical += [block]
    block = core.std.StackVertical(vertical)
    if clp.format.num_planes == 3:
        blockc = core.std.CropAbs(block, width=clp.width>>clp.format.subsampling_w, height=clp.height>>clp.format.subsampling_h)
        block = core.std.ShufflePlanes([block, blockc], planes=[0, 0, 0], colorfamily=clp.format.color_family)
    block = core.fmtc.bitdepth(block, bits=clp.format.bits_per_sample, fulls=False, fulld=True)
    block = core.std.Loop(block, clp.num_frames)
    
    # create normal deblocking (for block borders) and strong deblocking (for block interiour)
    normal = core.deblock.Deblock(clp, quant=quant1, aoffset=aOff1, boffset=bOff1, planes=[0, 1, 2] if uv!=2 else [0])
    strong = core.deblock.Deblock(clp, quant=quant2, aoffset=aOff2, boffset=bOff2, planes=[0, 1, 2] if uv!=2 else [0])
    
    # build difference maps of both
    normalD = core.std.MakeDiff(clp, normal, planes=planes)
    strongD = core.std.MakeDiff(clp, strong, planes=planes)
    
    # separate border values of the difference maps, and set the interiours to '128'
    expr = 'y {peak} = x {median} ?'.format(peak=peak, median=median)
    normalD2 = core.std.Expr([normalD, block], [expr] if uv==3 or clp.format.num_planes==1 else [expr, ''])
    strongD2 = core.std.Expr([strongD, block], [expr] if uv==3 or clp.format.num_planes==1 else [expr, ''])
    
    # interpolate the border values over the whole block: DCTFilter can do it. (Kiss to Tom Barry!)
    # (Note: this is not fully accurate, but a reasonable approximation.)
    # add borders if clp is not mod 16
    sw = strongD2.width
    sh = strongD2.height
    remX = 16 - sw % 16 if sw & 15 else 0
    remY = 16 - sh % 16 if sh & 15 else 0
    expr = 'x {median} - 1.01 * {median} +'.format(median=median)
    strongD3 = core.std.CropRel(
      core.dct.Filter(
        core.std.Expr([Resize(strongD2, sw+remX, sh+remY, 0, 0, sw+remX, sh+remY, kernel='point')], [expr] if uv==3 or clp.format.num_planes==1 else [expr, '']),
        [1, 1, 0, 0, 0, 0, 0, 0]),
      left=0, top=0, right=remX, bottom=remY)
    
    # apply compensation from "normal" deblocking to the borders of the full-block-compensations calculated from "strong" deblocking ...
    expr = 'y {median} = x y ?'.format(median=median)
    strongD4 = core.std.Expr([strongD3, normalD2], [expr] if uv==3 or clp.format.num_planes==1 else [expr, ''])
    
    # ... and apply it.
    deblocked = core.std.MakeDiff(clp, strongD4, planes=planes) 
    
    # simple decisions how to treat chroma
    if clp.format.num_planes == 3:
        if uv == -1:
            deblocked = core.std.Merge(deblocked, strong, weight=[0, 1])
        elif uv == 1:
            deblocked = core.std.Merge(deblocked, normal, weight=[0, 1])
    
    # remove mod 8 borders
    return core.std.CropRel(deblocked, left=0, top=0, right=padX, bottom=padY)


# rx, ry [float, 1.0 ... 2.0 ... ~3.0]
# As usual, the radii for halo removal.
# Note: this function is rather sensitive to the radius settings. Set it as low as possible! If radius is set too high, it will start missing small spots.
#
# darkkstr, brightstr [float, 0.0 ... 1.0] [<0.0 and >1.0 possible]
# The strength factors for processing dark and bright halos. Default 1.0 both for symmetrical processing.
# On Comic/Anime, darkstr=0.4~0.8 sometimes might be better ... sometimes. In General, the function seems to preserve dark lines rather good.
#
# lowsens, highsens [int, 0 ... 50 ... 100]
# Sensitivity settings, not that easy to describe them exactly ...
# In a sense, they define a window between how weak an achieved effect has to be to get fully accepted, and how strong an achieved effect has to be to get fully discarded.
# Defaults are 50 and 50 ... try and see for yourself.
#
# ss [float, 1.0 ... 1.5 ...]
# Supersampling factor, to avoid creation of aliasing.
#
# noring [bool]
# In case of supersampling, indicates that a non-ringing algorithm must be used.
def DeHalo_alpha(clp, rx=2., ry=2., darkstr=1., brightstr=1., lowsens=50, highsens=50, ss=1.5, noring=False):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode):
        raise ValueError('DeHalo_alpha: This is not a clip !')
    
    multiple = 2 ** (clp.format.bits_per_sample - 8)
    
    ox = clp.width
    oy = clp.height
    
    if clp.format.num_planes == 3:
        clp_src = clp
        clp = core.std.ShufflePlanes(clp, planes=[0], colorfamily=vs.GRAY)
    else:
        clp_src = None
    
    halos = Resize(Resize(clp, m4(ox/rx), m4(oy/ry), kernel='bicubic'), ox, oy, kernel='bicubic', a1=1, a2=0)
    are = core.std.Expr([core.generic.Maximum(clp), core.generic.Minimum(clp)], ['x y -'])
    ugly = core.std.Expr([core.generic.Maximum(halos), core.generic.Minimum(halos)], ['x y -'])
    expr = 'y {multiple} / x {multiple} / - y {multiple} / 0.001 + / 255 * {LOS} - y {multiple} / 256 + 512 / {HIS} + * {multiple} *'.format(multiple=multiple, LOS=lowsens, HIS=highsens/100)
    so = core.std.Expr([ugly, are], [expr])
    lets = core.std.MaskedMerge(halos, clp, so)
    if ss <= 1:
        remove = core.rgvs.Repair(clp, lets, 1)
    else:
        remove = Resize(
          core.std.Expr(
            [core.std.Expr([Resize(clp, m4(ox*ss), m4(oy*ss), kernel='spline64' if noring else 'spline36', noring=noring),
                            Resize(core.generic.Maximum(lets), m4(ox*ss), m4(oy*ss), kernel='bicubic')],
                           ['x y min']),
             Resize(core.generic.Minimum(lets), m4(ox*ss), m4(oy*ss), kernel='bicubic')],
            ['x y max']),
          ox, oy)
    them = core.std.Expr([clp, remove], ['x y < x x y - {DRK} * - x x y - {BRT} * - ?'.format(DRK=darkstr, BRT=brightstr)])
    
    if clp_src is not None:
        return core.std.ShufflePlanes([them, clp_src], planes=[0, 1, 2], colorfamily=clp_src.format.color_family)
    else:
        return them


# Y'et A'nother H'alo R'educing script
def YAHR(clp):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode) or clp.format.id != vs.YUV420P8:
        raise ValueError('YAHR: This is not a YUV420P8 clip !')
    
    b1 = core.rgvs.RemoveGrain(MinBlur(clp, 2, planes=[0]), [11, 0])
    b1D = core.std.MakeDiff(clp, b1, planes=[0])
    w1 = core.avs.aWarpSharp2(clp, depth=32, chroma=3)
    w1b1 = core.rgvs.RemoveGrain(MinBlur(w1, 2, planes=[0]), [11, 0])
    w1b1D = core.std.MakeDiff(w1, w1b1, planes=[0])
    DD = core.rgvs.Repair(b1D, w1b1D, [13, 0])
    DD2 = core.std.MakeDiff(b1D, DD, planes=[0])
    return core.std.MakeDiff(clp, DD2, planes=[0])


######
###
### HQDering mod v1.8      by mawen1250      2014.03.22
###
### Requirements: GenericFilters, RemoveGrain/Repair, CTMF
###
### Applies deringing by using a smart smoother near edges (where ringing occurs) only
###
### Parameters:
###  mrad [int]      - Expanding of edge mask, higher value means more aggressive processing. Default is 1
###  msmooth [int]   - Inflate of edge mask, smooth boundaries of mask. Default is 1
###  incedge [bool]  - Whether to include edge in ring mask, by default ring mask only include area near edges. Default is false
###  mthr [int]      - Threshold of sobel edge mask, lower value means more aggressive processing. Or define your own mask clip "ringmask".
###                    But for strong ringing, lower value will treat some ringing as edge, which protects this ringing from being processed. Default is 60
###  minp [int]      - Inpanding of sobel edge mask, higher value means more aggressive processing. Default is 1
###  nrmode [int]    - Kernel of dering - 1: MinBlur(radius=1), 2: MinBlur(radius=2), 3: MinBlur(radius=3). Or define your own smoothed clip "p". Default is 2 for HD / 1 for SD
###  nrmodec [int]   - Kernel of dering for chroma. Default is nrmode
###  sharp [int]     - Whether to use contra-sharpening to resharp deringed clip, 1-3 represents radius, 0 means no sharpening. Default is 1
###  drrep [int]     - Use repair for details retention, recommended values are 24/23/13/12/1. Default is 24
###  thr [float]     - The same meaning with "thr" in Dither_limit_dif16, valid value range is [0.0, 128.0]. Default is 12.0
###  elast [float]   - The same meaning with "elast" in Dither_limit_dif16, valid value range is [1.0, inf). Default is 2.0
###                    Larger "thr" will result in more pixels being taken from processed clip
###                    Larger "thr" will result in less pixels being taken from input clip
###                    Larger "elast" will result in more pixels being blended from processed&input clip, for smoother merging
###  darkthr [float] - Threshold for darker area near edges, set it lower if you think deringing destroys too much lines, etc. Default is thr/4
###                    When "darkthr" is not equal to "thr", "thr" limits darkening while "darkthr" limits brightening
###  Y,U,V [bool]    - If true, the corresponding plane is processed. Otherwise, it is copied through to the output image as is. Default is true,false,false
###  show [bool]     - Whether to output mask clip instead of filtered clip. Default is false
###
######
def HQDeringmod(input, p=None, ringmask=None, mrad=1, msmooth=1, incedge=False, mthr=60, minp=1, nrmode=None, nrmodec=None, sharp=1, drrep=24,
                thr=12., elast=2., darkthr=None, Y=True, U=False, V=False, show=False):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode):
        raise ValueError('HQDeringmod: This is not a clip !')
    if p is not None and (not isinstance(p, vs.VideoNode) or p.format.id != input.format.id):
        raise ValueError("HQDeringmod: 'p' must be the same format as input !")
    if ringmask is not None and not isinstance(ringmask, vs.VideoNode):
        raise ValueError("HQDeringmod: 'ringmask' is not a clip !")
    
    if nrmode is None:
        nrmode = 2 if input.width >= 1280 or input.height >= 720 else 1
    if nrmodec is None:
        nrmodec = nrmode
    if darkthr is None:
        darkthr = thr / 4
    
    if input.format.num_planes == 1:
        nrmodec = nrmode
        U = False
        V = False
    
    if Y and U and V:
        planes = [0, 1, 2]
    elif Y and U:
        planes = [0, 1]
    elif Y and V:
        planes = [0, 2]
    elif U and V:
        planes = [1, 2]
    elif Y:
        planes = [0]
    elif U:
        planes = [1]
    elif V:
        planes = [2]
    else:
        return input
    
    # Kernel: Smoothing
    if p is None:
        if nrmode == nrmodec:
            p = MinBlur(input, nrmode, planes=planes)
        else:
            if not Y:
                smoothl = input
            else:
                smoothl = MinBlur(input, nrmode, planes=[0])
            if not (U or V):
                smoothc = input
            else:
                smoothc = MinBlur(input, nrmodec, planes=[1, 2] if U and V else [1] if U else [2])
            p = core.std.Merge(smoothl, smoothc, weight=[0, 1])
    
    # Post-Process: Contra-Sharpening
    expr = 'x {median} - abs y {median} - abs <= x y ?'.format(median=1<<(input.format.bits_per_sample-1))
    if Y:
        Y4 = 4
        Y11 = 11
        Y20 = 20
        Yexpr = expr
    else:
        Y4 = Y11 = Y20 = 0
        Yexpr = ''
    if U:
        U4 = 4
        U11 = 11
        U20 = 20
        Uexpr = expr
    else:
        U4 = U11 = U20 = 0
        Uexpr = ''
    if V:
        V4 = 4
        V11 = 11
        V20 = 20
        Vexpr = expr
    else:
        V4 = V11 = V20 = 0
        Vexpr = ''
    M4 = [Y4] if input.format.num_planes == 1 else [Y4, U4, V4]
    M11 = [Y11] if input.format.num_planes == 1 else [Y11, U11, V11]
    M20 = [Y20] if input.format.num_planes == 1 else [Y20, U20, V20]
    
    if sharp <= 0:
        sclp = p
    else:
        pre = core.rgvs.RemoveGrain(p, M4)
        if sharp == 1:
            method = core.rgvs.RemoveGrain(pre, M11)
        elif sharp == 2:
            method = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(pre, M11), M20)
        else:
            method = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(pre, M11), M20), M20)
        sharpdiff = core.std.MakeDiff(pre, method, planes=planes)
        allD = core.std.MakeDiff(input, p, planes=planes)
        ssDD = core.rgvs.Repair(sharpdiff, allD, [1] if input.format.num_planes==1 else [1 if Y else 0, 1 if U else 0, 1 if V else 0])
        ssDD = core.std.Expr([ssDD, sharpdiff], [Yexpr] if input.format.num_planes==1 else [Yexpr, Uexpr, Vexpr])
        sclp = core.std.MergeDiff(p, ssDD, planes=planes)
    
    # Post-Process: Repairing
    if drrep <= 0:
        repclp = sclp
    else:
        repclp = core.rgvs.Repair(input, sclp, [drrep] if input.format.num_planes==1 else [drrep if Y else 0, drrep if U else 0, drrep if V else 0])
    
    # Post-Process: Limiting
    if (thr <= 0 and darkthr <= 0) or (thr >= 128 and darkthr >= 128):
        limitclp = repclp
    else:
        limitclp = LimitDiff(repclp, input, thr=thr, elast=elast, darkthr=darkthr, planes=planes)
    
    # Post-Process: Ringing Mask Generating
    if ringmask is None:
        sobelm = core.generic.Sobel(core.std.ShufflePlanes(input, planes=[0], colorfamily=vs.GRAY), mthr)
        fmask = core.generic.Hysteresis(core.rgvs.RemoveGrain(sobelm, 4), sobelm)
        if mrad > 0:
            omask = mt_expand_multi(fmask, sw=mrad, sh=mrad)
        else:
            omask = fmask
        if msmooth > 0:
            omask = mt_inflate_multi(omask, radius=msmooth)
        if incedge:
            ringmask = omask
        else:
            if minp > 3:
                imask = core.generic.Minimum(core.generic.Minimum(fmask))
            elif minp > 2:
                imask = core.generic.Minimum(core.generic.Minimum(core.generic.Inflate(fmask)))
            elif minp > 1:
                imask = core.generic.Minimum(fmask)
            elif minp > 0:
                imask = core.generic.Minimum(core.generic.Inflate(fmask))
            else:
                imask = fmask
            ringmask = core.std.Expr([omask, imask], ['x {peak} y - * {peak} /'.format(peak=(1<<input.format.bits_per_sample)-1)])
    
    # Mask Merging & Output
    if show:
        return ringmask
    else:
        return core.std.MaskedMerge(input, limitclp, ringmask, planes=planes)


#-------------------------------------------------------------------#
#                                                                   #
#                    QTGMC 3.33, by Vit, 2012                       #
#                                                                   #
#   A high quality deinterlacer using motion-compensated temporal   #
#  smoothing, with a range of features for quality and convenience  #
#          Originally based on TempGaussMC_beta2 by Didée           #
#                                                                   #
#-------------------------------------------------------------------#
#
# Full documentation is in the 'QTGMC' html file that comes with this script
#
# --- LATEST CHANGES ---
#
# v3.33
# - Increased maximum value for Rep0, Rep1 and Rep2 to 7 (from 5). Higher values help with flicker on static detail, potential for minor motion blur
# - Bug fix for the fact that Bob always outputs a BFF clip regardless of field order of input (thanks ajp_anton)
# - Improved generation of noise (NoiseDeint="Generate") for noise bypass / EZKeepGrain
# - Minor change to denoising
#
# --- REQUIREMENTS ---
#
# Input colorspaces: YUV420P8, YUV422P8
#
# Core plugins:
#	MVTools
#	GenericFilters
#	nnedi3
#	RemoveGrain/Repair
#   fmtconv
#   SceneChange
#
# Additional plugins:
#	eedi3 - if selected directly or via a source-match preset
#	FFT3DFilter - if selected for noise processing
#	dfttest - if selected for noise processing
#	FFT3dGPU - if selected for noise processing
#		For FFT3DFilter & ddftest you also need the FFTW3 library (FFTW.org). On Windows the file needed for both is libfftw3f-3.dll. However, for FFT3DFilter
#		the file needs to be called FFTW3.dll, so you will need two copies and rename one. On Windows put the files in your System32 or SysWow64 folder
#	AddGrain - if NoiseDeint="Generate" selected for noise bypass
#
# --- GETTING STARTED ---
#
# The "Preset" used selects sensible settings for a given encoding speed. Choose a preset from:
#	"Placebo", "Very Slow", "Slower", "Slow", "Medium", "Fast", "Faster", "Very Fast", "Super Fast", "Ultra Fast" & "Draft"
# The default preset is "Slower"
# Don't be obsessed with using slower settings as the differences can be small. HD material benefits little from extreme settings (and will be very slow)
# For much faster speeds read the full documentation, the section on 'Multi-threading'
#
# There are many settings for tweaking the script, full details in the main documentation. You can display settings currently being used with "ShowSettings":
#	QTGMC( Preset="Slow", ShowSettings=True )
def QTGMC(Input, Preset='Slower', TR0=None, TR1=None, TR2=None, Rep0=None, Rep1=0, Rep2=None, EdiMode=None, RepChroma=True, NNSize=None, NNeurons=None,
          EdiQual=1, EdiMaxD=None, ChromaEdi='', EdiExt=None, Sharpness=None, SMode=None, SLMode=None, SLRad=None, SOvs=0, SVThin=0., Sbb=None, SrchClipPP=None,
          SubPel=None, SubPelInterp=2, BlockSize=None, Overlap=None, Search=None, SearchParam=None, PelSearch=None, ChromaMotion=None, TrueMotion=False,
          Lambda=None, LSAD=None, PNew=None, PLevel=None, GlobalMotion=True, DCT=0, ThSAD1=640, ThSAD2=256, ThSCD1=180, ThSCD2=98, SourceMatch=0,
          MatchPreset=None, MatchEdi=None, MatchPreset2=None, MatchEdi2=None, MatchTR2=1, MatchEnhance=0.5, Lossless=0, NoiseProcess=None, EZDenoise=None,
          EZKeepGrain=None, NoisePreset='Fast', Denoiser=None, DenoiseThreads=0, DenoiseMC=None, NoiseTR=None, Sigma=None, ChromaNoise=False, ShowNoise=0.,
          GrainRestore=None, NoiseRestore=None, NoiseDeint=None, StabilizeNoise=None, InputType=0, ProgSADMask=None, FPSDivisor=1, ShutterBlur=0,
          ShutterAngleSrc=180, ShutterAngleOut=180, SBlurLimit=4, Border=False, Precise=None, Tuning='None', ShowSettings=False, ForceTR=0, TFF=None):
    core = vs.get_core()
    
    #---------------------------------------
    # Presets
    
    # Select presets / tuning
    Preset = Preset.lower()
    presets = ['placebo', 'very slow', 'slower', 'slow', 'medium', 'fast', 'faster', 'very fast', 'super fast', 'ultra fast', 'draft']
    try:
        pNum = presets.index(Preset)
    except:
        raise ValueError("QTGMC: 'Preset' choice is invalid")
    
    if MatchPreset is None:
        mpNum1 = pNum + 3 if pNum + 3 <= 9 else 9
        MatchPreset = presets[mpNum1]
    else:
        try:
            mpNum1 = presets[:10].index(MatchPreset.lower())
        except:
            raise ValueError("QTGMC: 'MatchPreset' choice is invalid/unsupported")
    
    if MatchPreset2 is None:
        mpNum2 = mpNum1 + 2 if mpNum1 + 2 <= 9 else 9
        MatchPreset2 = presets[mpNum2]
    else:
        try:
            mpNum2 = presets[:10].index(MatchPreset2.lower())
        except:
            raise ValueError("QTGMC: 'MatchPreset2' choice is invalid/unsupported")
    
    try:
        npNum = presets[2:7].index(NoisePreset.lower())
    except:
        raise ValueError("QTGMC: 'NoisePreset' choice is invalid")
    
    try:
        tNum = ['none', 'dv-sd', 'dv-hd'].index(Tuning.lower())
    except:
        raise ValueError("QTGMC: 'Tuning' choice is invalid")
    
    # Tunings only affect blocksize in this version
    bs = [16, 16, 32][tNum]
    bs2 = 32 if bs >= 16 else bs * 2
    
    #                                                   Very                                                              Very       Super      Ultra
    # Preset groups:                          Placebo   Slow       Slower     Slow       Medium     Fast       Faster     Fast       Fast       Fast       Draft
    if TR0          is None: TR0          = [ 2,        2,         2,         2,         2,         2,         1,         1,         1,         1,         0        ][pNum]
    if TR1          is None: TR1          = [ 2,        2,         2,         1,         1,         1,         1,         1,         1,         1,         1        ][pNum]
    if TR2 is not None:
        TR2X = TR2
    else:
        TR2X                              = [ 3,        2,         1,         1,         1,         0,         0,         0,         0,         0,         0        ][pNum]
    if Rep0         is None: Rep0         = [ 4,        4,         4,         4,         3,         3,         0,         0,         0,         0,         0        ][pNum]
    if Rep2         is None: Rep2         = [ 4,        4,         4,         4,         4,         4,         4,         4,         3,         3,         0        ][pNum]
    if EdiMode is not None:
        EdiMode = EdiMode.lower()
    else:
        EdiMode                           = ['nnedi3', 'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'nnedi3',  'bob'     ][pNum]
    if NNSize       is None: NNSize       = [ 1,        1,         1,         1,         5,         5,         4,         4,         4,         4,         4        ][pNum]
    if NNeurons     is None: NNeurons     = [ 2,        2,         1,         1,         1,         0,         0,         0,         0,         0,         0        ][pNum]
    if EdiMaxD      is None: EdiMaxD      = [ 12,       10,        8,         7,         7,         6,         6,         5,         4,         4,         4        ][pNum]
    ChromaEdi = ChromaEdi.lower()
    if SMode        is None: SMode        = [ 2,        2,         2,         2,         2,         2,         2,         2,         2,         2,         0        ][pNum]
    if SLMode is not None:
        SLModeX = SLMode
    else:
        SLModeX                           = [ 2,        2,         2,         2,         2,         2,         2,         2,         0,         0,         0        ][pNum]
    if SLRad        is None: SLRad        = [ 3,        1,         1,         1,         1,         1,         1,         1,         1,         1,         1        ][pNum]
    if Sbb          is None: Sbb          = [ 3,        1,         1,         0,         0,         0,         0,         0,         0,         0,         0        ][pNum]
    if SrchClipPP   is None: SrchClipPP   = [ 3,        3,         3,         3,         3,         2,         2,         2,         1,         1,         0        ][pNum]
    if SubPel       is None: SubPel       = [ 2,        2,         2,         2,         1,         1,         1,         1,         1,         1,         1        ][pNum]
    if BlockSize    is None: BlockSize    = [ bs,       bs,        bs,        bs,        bs,        bs,        bs2,       bs2,       bs2,       bs2,       bs2      ][pNum]
    bs = BlockSize
    if Overlap      is None: Overlap      = [int(bs/2), int(bs/2), int(bs/2), int(bs/2), int(bs/2), int(bs/2), int(bs/2), int(bs/4), int(bs/4), int(bs/4), int(bs/4)][pNum]
    if Search       is None: Search       = [ 5,        4,         4,         4,         4,         4,         4,         4,         0,         0,         0        ][pNum]
    if SearchParam  is None: SearchParam  = [ 2,        2,         2,         2,         2,         2,         2,         1,         1,         1,         1        ][pNum]
    if PelSearch    is None: PelSearch    = [ 2,        2,         2,         2,         1,         1,         1,         1,         1,         1,         1        ][pNum]
    if ChromaMotion is None: ChromaMotion = [ True,     True,      True,      False,     False,     False,     False,     False,     False,     False,     False    ][pNum]
    if Precise      is None: Precise      = [ True,     True,      False,     False,     False,     False,     False,     False,     False,     False,     False    ][pNum]
    if ProgSADMask  is None: ProgSADMask  = [ 10.,      10.,       10.,       10.,       10.,       0.,        0.,        0.,        0.,        0.,        0.       ][pNum]
    
    # Noise presets                               Slower      Slow       Medium     Fast      Faster
    if Denoiser is not None:
        Denoiser = Denoiser.lower()
    else:
        Denoiser                              = ['dfttest',  'dfttest', 'dfttest', 'fft3df', 'fft3df'][npNum]
    if DenoiseMC      is None: DenoiseMC      = [ True,       True,      False,     False,    False  ][npNum]
    if NoiseTR        is None: NoiseTR        = [ 2,          1,         1,         1,        0      ][npNum]
    if Denoiser == 'fft3dgpu' and NoiseTR == 2:
        NoiseTR = 1     # FFT3dGPU doesn't support bt=5, so restrict the maximum of NoiseTR to 1
    if NoiseDeint is not None:
        NoiseDeint = NoiseDeint.lower()
    else:
        NoiseDeint                            = ['generate', 'bob',      '',        '',       ''     ][npNum]
    if StabilizeNoise is None: StabilizeNoise = [ True,       True,      True,      False,    False  ][npNum]
    
    # The basic source-match step corrects and re-runs the interpolation of the input clip. So it initialy uses same interpolation settings as the main preset
    MatchNNSize = NNSize
    MatchNNeurons = NNeurons
    MatchEdiMaxD = EdiMaxD
    MatchEdiQual = EdiQual
    
    # However, can use a faster initial interpolation when using source-match allowing the basic source-match step to "correct" it with higher quality settings
    if SourceMatch > 0 and mpNum1 < pNum:
        raise ValueError("QTGMC: 'MatchPreset' cannot use a slower setting than 'Preset'")
    # Basic source-match presets
    if SourceMatch > 0:
        #                     Very                                            Very   Super   Ultra
        #           Placebo   Slow   Slower   Slow   Medium   Fast   Faster   Fast   Fast    Fast
        NNSize   = [1,        1,     1,       1,     5,       5,     4,       4,     4,      4][mpNum1]
        NNeurons = [2,        2,     1,       1,     1,       0,     0,       0,     0,      0][mpNum1]
        EdiMaxD  = [12,       10,    8,       7,     7,       6,     6,       5,     4,      4][mpNum1]
        EdiQual  = [1,        1,     1,       1,     1,       1,     1,       1,     1,      1][mpNum1]
    TempEdi = EdiMode   # Main interpolation is actually done by basic-source match step when enabled, so a little swap and wriggle is needed
    if SourceMatch > 0 and MatchEdi is not None:
        EdiMode = MatchEdi.lower()
    MatchEdi = TempEdi
    
    #                                             Very                                                        Very      Super    Ultra
    # Refined source-match presets      Placebo   Slow      Slower    Slow      Medium    Fast      Faster    Fast      Fast     Fast
    if MatchEdi2 is not None:
        MatchEdi2 = MatchEdi2.lower()
    else:
        MatchEdi2                   = ['nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', 'nnedi3', ''][mpNum2]
    MatchNNSize2                    = [ 1,        1,        1,        1,        5,        5,        4,        4,        4,       4 ][mpNum2]
    MatchNNeurons2                  = [ 2,        2,        1,        1,        1,        0,        0,        0,        0,       0 ][mpNum2]
    MatchEdiMaxD2                   = [ 12,       10,       8,        7,        7,        6,        6,        5,        4,       4 ][mpNum2]
    MatchEdiQual2                   = [ 1,        1,        1,        1,        1,        1,        1,        1,        1,       1 ][mpNum2]
    
    #---------------------------------------
    # Settings
    
    if not isinstance(Input, vs.VideoNode) or Input.format.id not in [vs.YUV420P8, vs.YUV422P8]:
        raise ValueError('QTGMC: This is not a YUV420P8/YUV422P8 clip !')
    if EdiExt is not None and (not isinstance(EdiExt, vs.VideoNode) or EdiExt.format.id != Input.format.id):
        raise ValueError("QTGMC: 'EdiExt' must be the same format as input !")
    if not isinstance(TFF, bool):
        raise ValueError("QTGMC: 'TFF' must be set. Setting TFF to true means top field first and false means bottom field first")
    
    # Core and Interpolation defaults
    if SourceMatch > 0 and TR2 is None:
        TR2 = 1 if TR2X <= 0 else TR2X  # ***TR2 defaults always at least 1 when using source-match***
    else:
        TR2 = TR2X
    if EdiMode == 'nnedi3' and EdiQual > 2:
        EdiQual = 2     # Smaller range for EdiQual in NNEDI3
    
    # Source-match defaults
    MatchTR1 = TR1
    
    # Sharpness defaults. Sharpness default is always 1.0 (0.2 with source-match), but adjusted to give roughly same sharpness for all settings
    if Sharpness is not None and Sharpness <= 0:
        SMode = 0
    if SourceMatch > 0:     # ***Sharpness limiting disabled by default for source-match***
        if SLMode is None:
            SLMode = 0
    else:
        SLMode = SLModeX
    if SLRad <= 0:
        SLMode = 0
    spatialSL = SLMode in [1, 3]
    temporalSL = SLMode in [2, 4]
    if Sharpness is None:
        Sharpness = 0. if SMode <= 0 else 0.2 if SourceMatch > 0 else 1.                                # Default sharpness is 1.0, or 0.2 if using source-match
    sharpMul = 2 if temporalSL else 1.5 if spatialSL else 1                                             # Adjust sharpness based on other settings
    sharpAdj = Sharpness * (sharpMul * (0.2 + TR1 * 0.15 + TR2 * 0.25) + (0.1 if SMode == 1 else 0))    # [This needs a bit more refinement]
    if SMode <= 0:
        Sbb = 0
    
    # Noise processing settings
    if EZDenoise is not None and EZDenoise > 0 and EZKeepGrain is not None and EZKeepGrain > 0:
        raise ValueError("QTGMC: EZDenoise and EZKeepGrain cannot be used together")
    if NoiseProcess is None:
        if EZDenoise is not None and EZDenoise > 0:
            NoiseProcess = 1
        elif (EZKeepGrain is not None and EZKeepGrain > 0) or Preset in ['placebo', 'very slow']:
            NoiseProcess = 2
        else:
            NoiseProcess = 0
    if GrainRestore is None:
        if EZDenoise is not None and EZDenoise > 0:
            GrainRestore = 0.
        elif EZKeepGrain is not None and EZKeepGrain > 0:
            GrainRestore = 0.3 * math.sqrt(EZKeepGrain)
        else:
            GrainRestore = [0., 0.7, 0.3][NoiseProcess]
    if NoiseRestore is None:
        if EZDenoise is not None and EZDenoise > 0:
            NoiseRestore = 0.
        elif EZKeepGrain is not None and EZKeepGrain > 0:
            NoiseRestore = 0.1 * math.sqrt(EZKeepGrain)
        else:
            NoiseRestore = [0., 0.3, 0.1][NoiseProcess]
    if Sigma is None:
        if EZDenoise is not None and EZDenoise > 0:
            Sigma = EZDenoise
        elif EZKeepGrain is not None and EZKeepGrain > 0:
            Sigma = 4. * EZKeepGrain
        else:
            Sigma = 2.
    if Denoiser in ['fft3df', 'fft3dfilter'] and DenoiseThreads <= 0:
        DenoiseThreads = 1  # FFT3DFilter doesn't support autodetection of number of logical processors on system
    if isinstance(ShowNoise, bool):
        ShowNoise = 10. if ShowNoise else 0.
    if ShowNoise > 0:
        NoiseProcess = 2
        NoiseRestore = 1.
    if NoiseProcess <= 0:
        NoiseTR = 0
        GrainRestore = 0.
        NoiseRestore = 0.
    totalRestore = GrainRestore + NoiseRestore
    if totalRestore <= 0:
        StabilizeNoise = False
    noiseTD = [1, 3, 5][NoiseTR]
    noiseCentre = '128' if Denoiser == 'dfttest' else '128.5'
    
    # MVTools settings
    if Lambda is None:
        Lambda = int((1000 if TrueMotion else 100) * BlockSize * BlockSize / 64)
    if LSAD is None:
        LSAD = 1200 if TrueMotion else 400
    if PNew is None:
        PNew = 50 if TrueMotion else 25
    if PLevel is None:
        PLevel = 1 if TrueMotion else 0
    
    # Motion blur settings
    if ShutterAngleOut * FPSDivisor == ShutterAngleSrc:     # If motion blur output is same as input
        ShutterBlur = 0
    
    # Miscellaneous
    if InputType < 2:
        ProgSADMask = 0.
    rgBlur = 11 if Precise else 12
    
    # Get maximum temporal radius needed
    maxTR = SLRad if temporalSL else 0
    if MatchTR2 > maxTR:
        maxTR = MatchTR2
    if TR1 > maxTR:
        maxTR = TR1
    if TR2 > maxTR:
        maxTR = TR2
    if NoiseTR > maxTR:
        maxTR = NoiseTR
    if (ProgSADMask > 0 or StabilizeNoise or ShutterBlur > 0) and maxTR < 1:
        maxTR = 1
    if ForceTR > maxTR:
        maxTR = ForceTR
    
    #---------------------------------------
    # Pre-Processing
    
    w = Input.width
    h = Input.height
    epsilon = 0.0001
    
    # Reverse "field" dominance for progressive repair mode 3 (only difference from mode 2)
    if InputType >= 3:
        TFF = not TFF
    
    # Pad vertically during processing (to prevent artefacts at top & bottom edges)
    if Border:
        clip = Resize(Input, w, h+8, 0, -4, 0, h+8+epsilon, kernel='point')
        h += 8
    else:
        clip = Input
    
    # Calculate padding needed for MVTools super clips to avoid crashes [fixed in latest MVTools, but keeping this code for a while]
    hpad = w - (int((w - Overlap) / (BlockSize - Overlap)) * (BlockSize - Overlap) + Overlap)
    vpad = h - (int((h - Overlap) / (BlockSize - Overlap)) * (BlockSize - Overlap) + Overlap)
    if hpad < 8:    # But match default padding if possible
        hpad = 8
    if vpad < 8:
        vpad = 8
    
    #---------------------------------------
    # Motion Analysis
    
    # Bob the input as a starting point for motion search clip
    if InputType <= 0:
        bobbed = Bob(clip, 0, 0.5, TFF)
    elif InputType == 1:
        bobbed = clip
    else:
        bobbed = core.generic.Blur(clip, 0, 0.5)
    
    CMts = 255 if ChromaMotion else 0
    CMrg = 12 if ChromaMotion else 0
    
    # The bobbed clip will shimmer due to being derived from alternating fields. Temporally smooth over the neighboring frames using a binomial kernel. Binomial
    # kernels give equal weight to even and odd frames and hence average away the shimmer. The two kernels used are [1 2 1] and [1 4 6 4 1] for radius 1 and 2.
    # These kernels are approximately Gaussian kernels, which work well as a prefilter before motion analysis (hence the original name for this script)
    # Create linear weightings of neighbors first                     -2    -1    0     1     2
    if TR0 > 0: ts1 = TemporalSoften(bobbed, 1, 255, CMts, 28, 2)   # 0.00  0.33  0.33  0.33  0.00
    if TR0 > 1: ts2 = TemporalSoften(bobbed, 2, 255, CMts, 28, 2)   # 0.20  0.20  0.20  0.20  0.20
    
    # Combine linear weightings to give binomial weightings - TR0=0: (1), TR0=1: (1:2:1), TR0=2: (1:4:6:4:1)
    if TR0 <= 0:
        binomial0 = bobbed
    elif TR0 == 1:
        binomial0 = core.std.Merge(ts1, bobbed, weight=[0.25] if ChromaMotion else [0.25, 0])
    else:
        binomial0 = core.std.Merge(core.std.Merge(ts1, ts2, weight=[0.357] if ChromaMotion else [0.357, 0]), bobbed,
                                   weight=[0.125] if ChromaMotion else [0.125, 0])
    
    # Remove areas of difference between temporal blurred motion search clip and bob that are not due to bob-shimmer - removes general motion blur
    if Rep0 <= 0:
        repair0 = binomial0
    else:
        repair0 = QTGMC_KeepOnlyBobShimmerFixes(binomial0, bobbed, Rep0, RepChroma and ChromaMotion)
    
    # x 7 + y < x 2 + x 7 - y > x 2 - x 51 * y 49 * + 100 / ? ?
    def get_lut(x, y):
        if x + 7 < y:
            return min(x + 2, 255)
        elif x - 7 > y:
            return max(x - 2, 0)
        else:
            return round((x * 51 + y * 49) / 100)
    
    # Blur image and soften edges to assist in motion matching of edge blocks. Blocks are matched by SAD (sum of absolute differences between blocks), but even
    # a slight change in an edge from frame to frame will give a high SAD due to the higher contrast of edges
    if SrchClipPP == 1:
        spatialBlur = Resize(core.rgvs.RemoveGrain(Resize(repair0, int(w/2), int(h/2), kernel='bilinear'), [12, CMrg]), w, h, kernel='bilinear')
    elif SrchClipPP >= 2:
        spatialBlur = Resize(core.rgvs.RemoveGrain(repair0, [12, CMrg]), w, h, 0, 0, w+epsilon, h+epsilon, kernel='gauss', a1=2)
    if SrchClipPP > 1:
        spatialBlur = core.std.Merge(spatialBlur, repair0, weight=[0.1] if ChromaMotion else [0.1, 0])
        expr = 'x 3 + y < x 3 + x 3 - y > x 3 - y ? ?'
        tweaked = core.std.Expr([repair0, bobbed], [expr] if ChromaMotion else [expr, ''])
    if SrchClipPP <= 0:
        srchClip = repair0
    elif SrchClipPP < 3:
        srchClip = spatialBlur
    else:
        srchClip = core.std.Lut2(spatialBlur, tweaked, planes=[0, 1, 2] if ChromaMotion else [0], function=get_lut)
    
    # Calculate forward and backward motion vectors from motion search clip
    if maxTR > 0:
        srchSuper = core.mv.Super(srchClip, pel=SubPel, sharp=SubPelInterp, hpad=hpad, vpad=vpad, chroma=ChromaMotion)
        bVec1 = core.mv.Analyse(
          srchSuper, isb=True, delta=1, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
        fVec1 = core.mv.Analyse(
          srchSuper, isb=False, delta=1, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
    if maxTR > 1:
        bVec2 = core.mv.Analyse(
          srchSuper, isb=True, delta=2, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
        fVec2 = core.mv.Analyse(
          srchSuper, isb=False, delta=2, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
    if maxTR > 2:
        bVec3 = core.mv.Analyse(
          srchSuper, isb=True, delta=3, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
        fVec3 = core.mv.Analyse(
          srchSuper, isb=False, delta=3, blksize=BlockSize, overlap=Overlap, search=Search, searchparam=SearchParam, pelsearch=PelSearch,
          truemotion=TrueMotion, _lambda=Lambda, lsad=LSAD, pnew=PNew, plevel=PLevel, _global=GlobalMotion, dct=DCT, chroma=ChromaMotion)
    
    #---------------------------------------
    # Noise Processing
    
    # Expand fields to full frame size before extracting noise (allows use of motion vectors which are frame-sized)
    if NoiseProcess > 0:
        if InputType > 0:
            fullClip = clip
        else:
            fullClip = Bob(clip, 0, 1, TFF)
    if NoiseTR > 0:
        fullSuper = core.mv.Super(fullClip, pel=SubPel, levels=1, hpad=hpad, vpad=vpad, chroma=ChromaNoise)     #TEST chroma OK?
    
    # Create a motion compensated temporal window around current frame and use to guide denoisers
    if NoiseProcess > 0:
        if not DenoiseMC or NoiseTR <= 0:
            noiseWindow = fullClip
        elif NoiseTR == 1:
            noiseWindow = core.std.Interleave([core.mv.Compensate(fullClip, fullSuper, fVec1, thscd1=ThSCD1, thscd2=ThSCD2),
                                               fullClip,
                                               core.mv.Compensate(fullClip, fullSuper, bVec1, thscd1=ThSCD1, thscd2=ThSCD2)])
        else:
            noiseWindow = core.std.Interleave([core.mv.Compensate(fullClip, fullSuper, fVec2, thscd1=ThSCD1, thscd2=ThSCD2),
                                               core.mv.Compensate(fullClip, fullSuper, fVec1, thscd1=ThSCD1, thscd2=ThSCD2),
                                               fullClip,
                                               core.mv.Compensate(fullClip, fullSuper, bVec1, thscd1=ThSCD1, thscd2=ThSCD2),
                                               core.mv.Compensate(fullClip, fullSuper, bVec2, thscd1=ThSCD1, thscd2=ThSCD2)])
        if Denoiser == 'dfttest':
            dnWindow = core.avs.dfttest(noiseWindow, U=ChromaNoise, V=ChromaNoise, sigma=Sigma*4, tbsize=noiseTD, threads=DenoiseThreads)
        elif Denoiser == 'fft3dgpu':
            dnWindow = core.avs.fft3dGPU(noiseWindow, plane=4 if ChromaNoise else 0, sigma=Sigma, bt=noiseTD, precision=2)
        else:
            dnWindow = core.avs.FFT3DFilter(noiseWindow, plane=4 if ChromaNoise else 0, sigma=Sigma, bt=noiseTD, ncpu=DenoiseThreads)
    
        # Rework denoised clip to match source format - various code paths here: discard the motion compensation window, discard doubled lines (from point resize)
        # Also reweave to get interlaced noise if source was interlaced (could keep the full frame of noise, but it will be poor quality from the point resize)
        if not DenoiseMC:
            if InputType > 0:
                denoised = dnWindow
            else:
                denoised = Weave(core.std.SelectEvery(core.std.SeparateFields(dnWindow, TFF), 4, [0, 3]), TFF)
        elif InputType > 0:
            if NoiseTR <= 0:
                denoised = dnWindow
            else:
                denoised = core.std.SelectEvery(dnWindow, noiseTD, [NoiseTR])
        else:
            denoised = Weave(core.std.SelectEvery(core.std.SeparateFields(dnWindow, TFF), noiseTD*4, [NoiseTR*2, NoiseTR*6+3]), TFF)
    
    CNplanes = [0, 1, 2] if ChromaNoise else [0]
    
    # Get actual noise from difference. Then 'deinterlace' where we have weaved noise - create the missing lines of noise in various ways
    if NoiseProcess > 0 and totalRestore > 0:
        noise = core.std.MakeDiff(clip, denoised, planes=CNplanes)
        if InputType > 0:
            deintNoise = noise
        elif NoiseDeint == 'bob':
            deintNoise = Bob(noise, 0, 0.5, TFF)
        elif NoiseDeint == 'generate':
            deintNoise = QTGMC_Generate2ndFieldNoise(noise, denoised, ChromaNoise, TFF)
        else:
            deintNoise = core.std.DoubleWeave(core.std.SeparateFields(noise, TFF), TFF)
        
        # Motion-compensated stabilization of generated noise
        if StabilizeNoise:
            noiseSuper = core.mv.Super(deintNoise, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad, chroma=ChromaNoise)
            mcNoise = core.mv.Compensate(deintNoise, noiseSuper, bVec1, thscd1=ThSCD1, thscd2=ThSCD2)
            expr = 'x 128 - abs y 128 - abs > x y ? 0.6 * x y + 0.2 * +'
            finalNoise = core.std.Expr([deintNoise, mcNoise], [expr] if ChromaNoise else [expr, ''])
        else:
            finalNoise = deintNoise
    
    # If NoiseProcess=1 denoise input clip. If NoiseProcess=2 leave noise in the clip and let the temporal blurs "denoise" it for a stronger effect
    innerClip = denoised if NoiseProcess == 1 else clip
    
    #---------------------------------------
    # Interpolation
    
    # Support badly deinterlaced progressive content - drop half the fields and reweave to get 1/2fps interlaced stream appropriate for QTGMC processing
    if InputType > 1:
        ediInput = Weave(core.std.SelectEvery(core.std.SeparateFields(innerClip, TFF), 4, [0, 3]), TFF)
    else:
        ediInput = innerClip
    
    # Create interpolated image as starting point for output
    if EdiExt is not None:
        edi1 = Resize(EdiExt, w, h, 0, (EdiExt.height-h)/2, 0, h+epsilon, kernel='point')
    else:
        edi1 = QTGMC_Interpolate(ediInput, InputType, EdiMode, NNSize, NNeurons, EdiQual, EdiMaxD, bobbed, ChromaEdi, TFF)
    
    # InputType=2,3: use motion mask to blend luma between original clip & reweaved clip based on ProgSADMask setting. Use chroma from original clip in any case
    if ProgSADMask > 0:
        inputTypeBlend = core.mv.Mask(srchClip, bVec1, kind=1, ml=ProgSADMask)
    if InputType < 2:
        edi = edi1
    elif ProgSADMask <= 0:
        edi = core.std.Merge(edi1, innerClip, weight=[0, 1])
    else:
        edi = core.std.MaskedMerge(innerClip, edi1, inputTypeBlend, planes=[0])
    
    # Get the max/min value for each pixel over neighboring motion-compensated frames - used for temporal sharpness limiting
    if TR1 > 0 or temporalSL:
        ediSuper = core.mv.Super(edi, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
    if temporalSL:
        bComp1 = core.mv.Compensate(edi, ediSuper, bVec1, thscd1=ThSCD1, thscd2=ThSCD2)
        fComp1 = core.mv.Compensate(edi, ediSuper, fVec1, thscd1=ThSCD1, thscd2=ThSCD2)
        tMax = core.std.Expr([core.std.Expr([edi, fComp1], ['x y max']), bComp1], ['x y max'])
        tMin = core.std.Expr([core.std.Expr([edi, fComp1], ['x y min']), bComp1], ['x y min'])
        if SLRad > 1:
            bComp3 = core.mv.Compensate(edi, ediSuper, bVec3, thscd1=ThSCD1, thscd2=ThSCD2)
            fComp3 = core.mv.Compensate(edi, ediSuper, fVec3, thscd1=ThSCD1, thscd2=ThSCD2)
            tMax = core.std.Expr([core.std.Expr([tMax, fComp3], ['x y max']), bComp3], ['x y max'])
            tMin = core.std.Expr([core.std.Expr([tMin, fComp3], ['x y min']), bComp3], ['x y min'])
    
    #---------------------------------------
    # Create basic output
    
    # Use motion vectors to blur interpolated image (edi) with motion-compensated previous and next frames. As above, this is done to remove shimmer from
    # alternate frames so the same binomial kernels are used. However, by using motion-compensated smoothing this time we avoid motion blur. The use of
    # MDegrain1 (motion compensated) rather than TemporalSmooth makes the weightings *look* different, but they evaluate to the same values
    # Create linear weightings of neighbors first                                                                         -2    -1    0     1     2
    if TR1 > 0: degrain1 = core.mv.Degrain1(edi, ediSuper, bVec1, fVec1, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)    # 0.00  0.33  0.33  0.33  0.00
    if TR1 > 1: degrain2 = core.mv.Degrain1(edi, ediSuper, bVec2, fVec2, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)    # 0.33  0.00  0.33  0.00  0.33
    
    # Combine linear weightings to give binomial weightings - TR1=0: (1), TR1=1: (1:2:1), TR1=2: (1:4:6:4:1)
    if TR1 <= 0:
        binomial1 = edi
    elif TR1 == 1:
        binomial1 = core.std.Merge(degrain1, edi, weight=[0.25])
    else:
        binomial1 = core.std.Merge(core.std.Merge(degrain1, degrain2, weight=[0.2]), edi, weight=[0.0625])
    
    # Remove areas of difference between smoothed image and interpolated image that are not bob-shimmer fixes: repairs residual motion blur from temporal smooth
    if Rep1 <= 0:
        repair1 = binomial1
    else:
        repair1 = QTGMC_KeepOnlyBobShimmerFixes(binomial1, edi, Rep1, RepChroma)
    
    # Apply source match - use difference between output and source to succesively refine output [extracted to function to clarify main code path]
    if SourceMatch <= 0:
        match = repair1
    else:
        match = QTGMC_ApplySourceMatch(repair1, InputType, ediInput, bVec1 if maxTR>0 else None, fVec1 if maxTR>0 else None, bVec2 if maxTR>1 else None,
                                       fVec2 if maxTR>1 else None, SubPel, SubPelInterp, hpad, vpad, ThSAD1, ThSCD1, ThSCD2, SourceMatch, MatchTR1, MatchEdi,
                                       MatchNNSize, MatchNNeurons, MatchEdiQual, MatchEdiMaxD, MatchTR2, MatchEdi2, MatchNNSize2, MatchNNeurons2, MatchEdiQual2,
                                       MatchEdiMaxD2, MatchEnhance, TFF)
    
    # Lossless=2 - after preparing an interpolated, de-shimmered clip, restore the original source fields into it and clean up any artefacts.
    # This mode will not give a true lossless result because the resharpening and final temporal smooth are still to come, but it will add further detail.
    # However, it can introduce minor combing. This setting is best used together with source-match (it's effectively the final source-match stage)
    if Lossless >= 2:
        lossed1 = QTGMC_MakeLossless(match, innerClip, InputType, TFF)
    else:
        lossed1 = match
    
    #---------------------------------------
    # Resharpen / retouch output
    
    # Resharpen to counteract temporal blurs. Little sharpening needed for source-match mode since it has already recovered sharpness from source
    if SMode >= 2:
        vresharp1 = core.std.Merge(core.generic.Maximum(lossed1, coordinates=[0, 1, 0, 0, 0, 0, 1, 0]),
                                   core.generic.Minimum(lossed1, coordinates=[0, 1, 0, 0, 0, 0, 1, 0]))
        if Precise:     # Precise mode: reduce tiny overshoot
            vresharp = core.std.Expr([vresharp1, lossed1], ['x y < x 1 + x y > x 1 - x ? ?'])
        else:
            vresharp = vresharp1
    if SMode <= 0:
        resharp = lossed1
    elif SMode == 1:
        resharp = core.std.Expr([lossed1, core.rgvs.RemoveGrain(lossed1, rgBlur)], ['x x y - {sharpAdj} * +'.format(sharpAdj=sharpAdj)])
    else:
        resharp = core.std.Expr([lossed1, core.rgvs.RemoveGrain(vresharp, rgBlur)], ['x x y - {sharpAdj} * +'.format(sharpAdj=sharpAdj)])
    
    # Slightly thin down 1-pixel high horizontal edges that have been widened into neigboring field lines by the interpolator
    SVThinSc = SVThin * 6.
    if SVThin > 0:
        vertMedD = core.std.Expr([lossed1, core.rgvs.VerticalCleaner(lossed1, [1, 0])], ['y x - {SVThinSc} * 128 +'.format(SVThinSc=SVThinSc), ''])
        vertMedD = core.generic.Blur(vertMedD, 0.5, 0)
        neighborD = core.std.Expr([vertMedD, core.rgvs.RemoveGrain(vertMedD, [rgBlur, 0])], ['y 128 - abs x 128 - abs > y 128 ?', ''])
        thin = core.std.MergeDiff(resharp, neighborD, planes=[0])
    else:
        thin = resharp
    
    # Back blend the blurred difference between sharpened & unsharpened clip, before (1st) sharpness limiting (Sbb == 1,3). A small fidelity improvement
    if Sbb not in [1, 3]:
        backBlend1 = thin
    else:
        backBlend1 = core.std.MakeDiff(thin,
                                       Resize(core.rgvs.RemoveGrain(core.std.MakeDiff(thin, lossed1, planes=[0]), [12, 0]),
                                              w, h, 0, 0, w+epsilon, h+epsilon, kernel='gauss', a1=5),
                                       planes=[0])
    
    # Limit over-sharpening by clamping to neighboring (spatial or temporal) min/max values in original
    # Occurs here (before final temporal smooth) if SLMode == 1,2. This location will restrict sharpness more, but any artefacts introduced will be smoothed
    if SLMode == 1:
        if SLRad <= 1:
            sharpLimit1 = core.rgvs.Repair(backBlend1, edi, 1)
        else:
            sharpLimit1 = core.rgvs.Repair(backBlend1, core.rgvs.Repair(backBlend1, edi, 12), 1)
    elif SLMode == 2:
        sharpLimit1 = Clamp(backBlend1, tMax, tMin, SOvs, SOvs)
    else:
        sharpLimit1 = backBlend1
    
    # Back blend the blurred difference between sharpened & unsharpened clip, after (1st) sharpness limiting (Sbb == 2,3). A small fidelity improvement
    if Sbb < 2:
        backBlend2 = sharpLimit1
    else:
        backBlend2 = core.std.MakeDiff(sharpLimit1,
                                       Resize(core.rgvs.RemoveGrain(core.std.MakeDiff(sharpLimit1, lossed1, planes=[0]), [12, 0]),
                                              w, h, 0, 0, w+epsilon, h+epsilon, kernel='gauss', a1=5),
                                       planes=[0])
    
    # Add back any extracted noise, prior to final temporal smooth - this will restore detail that was removed as "noise" without restoring the noise itself
    # Average luma of FFT3DFilter extracted noise is 128.5, so deal with that too
    if GrainRestore <= 0:
        addNoise1 = backBlend2
    else:
        expr = 'x {noiseCentre} - {GrainRestore} * 128 +'.format(noiseCentre=noiseCentre, GrainRestore=GrainRestore)
        addNoise1 = core.std.MergeDiff(backBlend2, core.std.Expr([finalNoise], [expr] if ChromaNoise else [expr, '']), planes=CNplanes)
    
    # Final light linear temporal smooth for denoising
    if TR2 > 0:
        stableSuper = core.mv.Super(addNoise1, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
    if TR2 <= 0:
        stable = addNoise1
    elif TR2 == 1:
        stable = core.mv.Degrain1(addNoise1, stableSuper, bVec1, fVec1, thsad=ThSAD2, thscd1=ThSCD1, thscd2=ThSCD2)
    elif TR2 == 2:
        stable = core.mv.Degrain2(addNoise1, stableSuper, bVec1, fVec1, bVec2, fVec2, thsad=ThSAD2, thscd1=ThSCD1, thscd2=ThSCD2)
    else:
        stable = core.mv.Degrain3(addNoise1, stableSuper, bVec1, fVec1, bVec2, fVec2, bVec3, fVec3, thsad=ThSAD2, thscd1=ThSCD1, thscd2=ThSCD2)
    
    # Remove areas of difference between final output & basic interpolated image that are not bob-shimmer fixes: repairs motion blur caused by temporal smooth
    if Rep2 <= 0:
        repair2 = stable
    else:
        repair2 = QTGMC_KeepOnlyBobShimmerFixes(stable, edi, Rep2, RepChroma)
    
    # Limit over-sharpening by clamping to neighboring (spatial or temporal) min/max values in original
    # Occurs here (after final temporal smooth) if SLMode == 3,4. Allows more sharpening here, but more prone to introducing minor artefacts
    if SLMode == 3:
        if SLRad <= 1:
            sharpLimit2 = core.rgvs.Repair(repair2, edi, 1)
        else:
            sharpLimit2 = core.rgvs.Repair(repair2, core.rgvs.Repair(repair2, edi, 12), 1)
    elif SLMode >= 4:
        sharpLimit2 = Clamp(repair2, tMax, tMin, SOvs, SOvs)
    else:
        sharpLimit2 = repair2
    
    # Lossless=1 - inject source fields into result and clean up inevitable artefacts. Provided NoiseRestore=0.0 or 1.0, this mode will make the script result
    # properly lossless, but this will retain source artefacts and cause some combing (where the smoothed deinterlace doesn't quite match the source)
    if Lossless == 1:
        lossed2 = QTGMC_MakeLossless(sharpLimit2, innerClip, InputType, TFF)
    else:
        lossed2 = sharpLimit2
    
    # Add back any extracted noise, after final temporal smooth. This will appear as noise/grain in the output
    # Average luma of FFT3DFilter extracted noise is 128.5, so deal with that too
    if NoiseRestore <= 0:
        addNoise2 = lossed2
    else:
        expr = 'x {noiseCentre} - {NoiseRestore} * 128 +'.format(noiseCentre=noiseCentre, NoiseRestore=NoiseRestore)
        addNoise2 = core.std.MergeDiff(lossed2, core.std.Expr([finalNoise], [expr] if ChromaNoise else [expr, '']), planes=CNplanes)
    
    #---------------------------------------
    # Post-Processing
    
    # Shutter motion blur - get level of blur depending on output framerate and blur already in source
    blurLevel = (ShutterAngleOut * FPSDivisor - ShutterAngleSrc) * 100 / 360
    if blurLevel < 0:
        raise ValueError('QTGMC: Cannot reduce motion blur already in source: increase ShutterAngleOut or FPSDivisor')
    elif blurLevel > 200:
        raise ValueError('QTGMC: Exceeded maximum motion blur level: decrease ShutterAngleOut or FPSDivisor')
    
    # ShutterBlur mode 2,3 - get finer resolution motion vectors to reduce blur "bleeding" into static areas
    rBlockDivide = [1, 1, 2, 4][ShutterBlur]
    rBlockSize = int(BlockSize / rBlockDivide)
    rOverlap = int(Overlap / rBlockDivide)
    if rBlockSize < 4:
        rBlockSize = 4
    if rOverlap < 2:
        rOverlap = 2
    rBlockDivide = int(BlockSize / rBlockSize)
    rLambda = int(Lambda / (rBlockDivide * rBlockDivide))
    if ShutterBlur > 1:
        sbBVec1 = core.mv.Recalculate(srchSuper, bVec1, thsad=ThSAD1, blksize=rBlockSize, overlap=rOverlap, search=Search, searchparam=SearchParam,
                                      truemotion=TrueMotion, _lambda=rLambda, pnew=PNew, chroma=ChromaMotion)
        sbFVec1 = core.mv.Recalculate(srchSuper, fVec1, thsad=ThSAD1, blksize=rBlockSize, overlap=rOverlap, search=Search, searchparam=SearchParam,
                                      truemotion=TrueMotion, _lambda=rLambda, pnew=PNew, chroma=ChromaMotion)
    elif ShutterBlur > 0:
        sbBVec1 = bVec1
        sbFVec1 = fVec1
    
    # Shutter motion blur - use MFlowBlur to blur along motion vectors
    if ShutterBlur > 0:
        sblurSuper = core.mv.Super(addNoise2, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
        sblur = core.mv.FlowBlur(addNoise2, sblurSuper, sbBVec1, sbFVec1, blur=blurLevel, thscd1=ThSCD1, thscd2=ThSCD2)
    
    # Shutter motion blur - use motion mask to reduce blurring in areas of low motion - also helps reduce blur "bleeding" into static areas, then select blur type
    if ShutterBlur > 0 and SBlurLimit > 0:
        sbMotionMask = core.mv.Mask(srchClip, bVec1, kind=0, ml=SBlurLimit)
    if ShutterBlur <= 0:
        sblurred = addNoise2
    elif SBlurLimit <= 0:
        sblurred = sblur
    else:
        sblurred = core.std.MaskedMerge(addNoise2, sblur, sbMotionMask)
    
    # Reduce frame rate
    if FPSDivisor > 1:
        decimated = core.std.SelectEvery(sblurred, FPSDivisor, [0])
    else:
        decimated = sblurred
    
    # Crop off temporary vertical padding
    if Border:
        cropped = core.std.CropRel(decimated, left=0, top=4, right=0, bottom=4)
        h -= 8
    else:
        cropped = decimated
    
    # Show output of choice + settings
    if ShowNoise <= 0:
        output = cropped
    else:
        expr = 'x 128 - {ShowNoise} * 128 +'.format(ShowNoise=ShowNoise)
        output = core.std.Expr([finalNoise], [expr] if ChromaNoise else [expr, '128'])
    if not ShowSettings:
        return output
    else:
        text = "TR0={} | TR1={} | TR2={} | Rep0={} | Rep1={} | Rep2={} | RepChroma={} | EdiMode='{}' | NNSize={} | NNeurons={} | EdiQual={} | EdiMaxD={} | " + \
               "ChromaEdi='{}' | Sharpness={} | SMode={} | SLMode={} | SLRad={} | SOvs={} | SVThin={} | Sbb={} | SrchClipPP={} | SubPel={}" + \
               " | SubPelInterp={} | BlockSize={} | Overlap={} | Search={} | SearchParam={} | PelSearch={} | ChromaMotion={} | TrueMotion={} | Lambda={} | " + \
               "LSAD={} | PNew={} | PLevel={} | GlobalMotion={} | DCT={} | ThSAD1={} | ThSAD2={} | ThSCD1={} | ThSCD2={} | SourceMatch={} | " + \
               "MatchPreset='{}' | MatchEdi='{}' | MatchPreset2='{}' | MatchEdi2='{}' | MatchTR2={} | MatchEnhance={} | Lossless={} | NoiseProcess={} | " + \
               "Denoiser='{}' | DenoiseThreads={} | DenoiseMC={} | NoiseTR={} | Sigma={} | ChromaNoise={} | ShowNoise={} | GrainRestore={} | " + \
               "NoiseRestore={} | NoiseDeint='{}' | StabilizeNoise={} | InputType={} | ProgSADMask={} | FPSDivisor={} | ShutterBlur={} | ShutterAngleSrc={}" + \
               " | ShutterAngleOut={} | SBlurLimit={} | Border={} | Precise={} | Preset='{}' | Tuning='{}' | ForceTR={}"
        text = text.format(TR0, TR1, TR2, Rep0, Rep1, Rep2, RepChroma, EdiMode, NNSize, NNeurons, EdiQual, EdiMaxD, ChromaEdi, Sharpness, SMode,
                           SLMode, SLRad, SOvs, SVThin, Sbb, SrchClipPP, SubPel, SubPelInterp, BlockSize, Overlap, Search, SearchParam, PelSearch, ChromaMotion,
                           TrueMotion, Lambda, LSAD, PNew, PLevel, GlobalMotion, DCT, ThSAD1, ThSAD2, ThSCD1, ThSCD2, SourceMatch, MatchPreset, MatchEdi,
                           MatchPreset2, MatchEdi2, MatchTR2, MatchEnhance, Lossless, NoiseProcess, Denoiser, DenoiseThreads, DenoiseMC, NoiseTR, Sigma,
                           ChromaNoise, ShowNoise, GrainRestore, NoiseRestore, NoiseDeint, StabilizeNoise, InputType, ProgSADMask, FPSDivisor, ShutterBlur,
                           ShutterAngleSrc, ShutterAngleOut, SBlurLimit, Border, Precise, Preset, Tuning, ForceTR)
        return core.text.Text(output, text)

#---------------------------------------
# Helpers

# Interpolate input clip using method given in EdiMode. Use Fallback or Bob as result if mode not in list. If ChromaEdi string if set then interpolate chroma
# separately with that method (only really useful for EEDIx). The function is used as main algorithm starting point and for first two source-match stages
def QTGMC_Interpolate(Input, InputType, EdiMode, NNSize, NNeurons, EdiQual, EdiMaxD, Fallback=None, ChromaEdi='', TFF=None):
    core = vs.get_core()
    
    CEed = ChromaEdi == ''
    planes = [0, 1, 2] if CEed else [0]
    field = 3 if TFF else 2
    
    if InputType == 1:
        return Input
    elif EdiMode == 'nnedi3':
        interp = core.nnedi3.nnedi3(Input, field=field, U=CEed, V=CEed, nsize=NNSize, nns=NNeurons, qual=EdiQual)
    elif EdiMode == 'eedi3+nnedi3':
        interp = core.eedi3.eedi3(Input, field=field, planes=planes, mdis=EdiMaxD,
                                  sclip=core.nnedi3.nnedi3(Input, field=field, U=CEed, V=CEed, nsize=NNSize, nns=NNeurons, qual=EdiQual))
    elif EdiMode == 'eedi3':
        interp = core.eedi3.eedi3(Input, field=field, planes=planes, mdis=EdiMaxD)
    else:
        if isinstance(Fallback, vs.VideoNode):
            interp = Fallback
        else:
            interp = Bob(Input, 0, 0.5, TFF)
    
    if ChromaEdi == 'nnedi3':
        interpuv = core.nnedi3.nnedi3(Input, field=field, Y=False, nsize=4, nns=0, qual=1)
    elif ChromaEdi == 'bob':
        interpuv = Bob(Input, 0, 0.5, TFF)
    else:
        return interp
    
    return core.std.Merge(interp, interpuv, weight=[0, 1])

# Helper function: Compare processed clip with reference clip: only allow thin, horizontal areas of difference, i.e. bob shimmer fixes
# Rough algorithm: Get difference, deflate vertically by a couple of pixels or so, then inflate again. Thin regions will be removed
#                  by this process. Restore remaining areas of difference back to as they were in reference clip
def QTGMC_KeepOnlyBobShimmerFixes(Input, Ref, Rep=1, Chroma=True):
    core = vs.get_core()
    
    # ed is the erosion distance - how much to deflate then reflate to remove thin areas of interest: 0 = minimum to 6 = maximum
    # od is over-dilation level  - extra inflation to ensure areas to restore back are fully caught:  0 = none to 3 = one full pixel
    # If Rep < 10, then ed = Rep and od = 0, otherwise ed = 10s digit and od = 1s digit (nasty method, but kept for compatibility with original TGMC)
    ed = Rep if Rep < 10 else int(Rep / 10)
    od = 0 if Rep < 10 else Rep % 10
    planes = [0, 1, 2] if Chroma else [0]
    
    diff = core.std.MakeDiff(Ref, Input)
    
    # Areas of positive difference                                                                          # ed = 0 1 2 3 4 5 6 7
    choke1 = core.generic.Minimum(diff, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])                #      x x x x x x x x    1 pixel   \
    if ed > 2: choke1 = core.generic.Minimum(choke1, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])   #      . . . x x x x x    1 pixel    |  Deflate to remove thin areas
    if ed > 5: choke1 = core.generic.Minimum(choke1, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])   #      . . . . . . x x    1 pixel   /
    if ed % 3 != 0: choke1 = core.generic.Deflate(choke1, planes=planes)                                    #      . x x . x x . x    A bit more deflate & some horizonal effect
    if ed in [2, 5]: choke1 = core.rgvs.RemoveGrain(choke1, 4)                                              #      . . x . . x . .    Local median
    choke1 = core.generic.Maximum(choke1, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])              #      x x x x x x x x    1 pixel  \
    if ed > 1: choke1 = core.generic.Maximum(choke1, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])   #      . . x x x x x x    1 pixel   | Reflate again
    if ed > 4: choke1 = core.generic.Maximum(choke1, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])   #      . . . . . x x x    1 pixel  /
    
    # Over-dilation - extra reflation up to about 1 pixel
    if od == 1:
        choke1 = core.generic.Inflate(choke1, planes=planes)
    elif od == 2:
        choke1 = core.generic.Inflate(core.generic.Inflate(choke1, planes=planes), planes=planes)
    elif od >= 3:
        choke1 = core.generic.Maximum(choke1, planes=planes)
    
    # Areas of negative difference (similar to above)
    choke2 = core.generic.Maximum(diff, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if ed > 2:
        choke2 = core.generic.Maximum(choke2, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if ed > 5:
        choke2 = core.generic.Maximum(choke2, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if ed % 3 != 0:
        choke2 = core.generic.Inflate(choke2, planes=planes)
    if ed in [2, 5]:
        choke2 = core.rgvs.RemoveGrain(choke2, 4)
    choke2 = core.generic.Minimum(choke2, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if ed > 1:
        choke2 = core.generic.Minimum(choke2, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if ed > 4:
        choke2 = core.generic.Minimum(choke2, planes=planes, coordinates=[0, 1, 0, 0, 0, 0, 1, 0])
    if od == 1:
        choke2 = core.generic.Deflate(choke2, planes=planes)
    elif od == 2:
        choke2 = core.generic.Deflate(core.generic.Deflate(choke2, planes=planes), planes=planes)
    elif od >= 3:
        choke2 = core.generic.Minimum(choke2, planes=planes)
    
    # Combine above areas to find those areas of difference to restore
    expr1 = 'x 129 < x y 128 < 128 y ? ?'
    expr2 = 'x 127 > x y 128 > 128 y ? ?'
    restore = core.std.Expr([core.std.Expr([diff, choke1], [expr1] if Chroma else [expr1, '']), choke2], [expr2] if Chroma else [expr2, ''])
    
    return core.std.MergeDiff(Input, restore, planes=planes)

# Given noise extracted from an interlaced source (i.e. the noise is interlaced), generate "progressive" noise with a new "field" of noise injected. The new
# noise is centered on a weighted local average and uses the difference between local min & max as an estimate of local variance
def QTGMC_Generate2ndFieldNoise(Input, InterleavedClip, ChromaNoise=False, TFF=None):
    core = vs.get_core()
    
    planes = [0, 1, 2] if ChromaNoise else [0]
    origNoise = core.std.SeparateFields(Input, TFF)
    noiseMax = core.generic.Maximum(core.generic.Maximum(origNoise, planes=planes), planes=planes, coordinates=[0, 0, 0, 1, 1, 0, 0, 0])
    noiseMin = core.generic.Minimum(core.generic.Minimum(origNoise, planes=planes), planes=planes, coordinates=[0, 0, 0, 1, 1, 0, 0, 0])
    random = core.grain.Add(core.std.BlankClip(core.std.SeparateFields(InterleavedClip, TFF), color=[128, 128, 128]), var=1800, uvar=1800 if ChromaNoise else 0)
    expr = 'x 128 - y * 256 / 128 +'
    varRandom = core.std.Expr([core.std.MakeDiff(noiseMax, noiseMin, planes=planes), random], [expr] if ChromaNoise else [expr, ''])
    newNoise = core.std.MergeDiff(noiseMin, varRandom, planes=planes)
    return Weave(core.std.Interleave([origNoise, newNoise]), TFF)

# Insert the source lines into the result to create a true lossless output. However, the other lines in the result have had considerable processing and won't
# exactly match source lines. There will be some slight residual combing. Use vertical medians to clean a little of this away
def QTGMC_MakeLossless(Input, Source, InputType, TFF):
    core = vs.get_core()
    
    if InputType == 1:
        raise ValueError('QTGMC: Lossless modes are incompatible with InputType=1')
    
    # Weave the source fields and the "new" fields that have generated in the input
    if InputType <= 0:
        srcFields = core.std.SeparateFields(Source, TFF)
    else:
        srcFields = core.std.SelectEvery(core.std.SeparateFields(Source, TFF), 4, [0, 3])
    newFields = core.std.SelectEvery(core.std.SeparateFields(Input, TFF), 4, [1, 2])
    processed = Weave(core.std.SelectEvery(core.std.Interleave([srcFields, newFields]), 4, [0, 1, 3, 2]), TFF)
    
    # x 128 - y 128 - * 0 < 128 x 128 - abs y 128 - abs < x y ? ?
    def get_lut(x, y):
        if (x - 128) * (y - 128) < 0:
            return 128
        elif abs(x - 128) < abs(y - 128):
            return x
        else:
            return y
    
    # Clean some of the artefacts caused by the above - creating a second version of the "new" fields
    vertMedian = core.rgvs.VerticalCleaner(processed, 1)
    vertMedDiff = core.std.MakeDiff(processed, vertMedian)
    vmNewDiff1 = core.std.SelectEvery(core.std.SeparateFields(vertMedDiff, TFF), 4, [1, 2])
    vmNewDiff2 = core.std.Lut2(core.rgvs.VerticalCleaner(vmNewDiff1, 1), vmNewDiff1, function=get_lut)
    vmNewDiff3 = core.rgvs.Repair(vmNewDiff2, core.rgvs.RemoveGrain(vmNewDiff2, 2), 1)
    
    # Reweave final result
    return Weave(core.std.SelectEvery(core.std.Interleave([srcFields, core.std.MakeDiff(newFields, vmNewDiff3)]), 4, [0, 1, 3, 2]), TFF)

# Source-match, a three stage process that takes the difference between deinterlaced input and the original interlaced source, to shift the input more towards
# the source without introducing shimmer. All other arguments defined in main script
def QTGMC_ApplySourceMatch(Deinterlace, InputType, Source, bVec1, fVec1, bVec2, fVec2, SubPel, SubPelInterp, hpad, vpad, ThSAD1, ThSCD1, ThSCD2,
                           SourceMatch, MatchTR1, MatchEdi, MatchNNSize, MatchNNeurons, MatchEdiQual, MatchEdiMaxD,
                           MatchTR2, MatchEdi2, MatchNNSize2, MatchNNeurons2, MatchEdiQual2, MatchEdiMaxD2, MatchEnhance, TFF):
    core = vs.get_core()
    
    # Basic source-match. Find difference between source clip & equivalent fields in interpolated/smoothed clip (called the "error" in formula below). Ideally
    # there should be no difference, we want the fields in the output to be as close as possible to the source whilst remaining shimmer-free. So adjust the
    # *source* in such a way that smoothing it will give a result closer to the unadjusted source. Then rerun the interpolation (edi) and binomial smooth with
    # this new source. Result will still be shimmer-free and closer to the original source.
    # Formula used for correction is P0' = P0 + (P0-P1)/(k+S(1-k)), where P0 is original image, P1 is the 1st attempt at interpolation/smoothing , P0' is the
    # revised image to use as new source for interpolation/smoothing, k is the weighting given to the current frame in the smooth, and S is a factor indicating
    # "temporal similarity" of the error from frame to frame, i.e. S = average over all pixels of [neighbor frame error / current frame error] . Decreasing
    # S will make the result sharper, sensible range is about -0.25 to 1.0. Empirically, S=0.5 is effective [will do deeper analysis later]
    errorTemporalSimilarity = 0.5   # S in formula described above
    errorAdjust1 = [1, 2/(1+errorTemporalSimilarity), 8/(3+5*errorTemporalSimilarity)][MatchTR1]
    if SourceMatch < 1 or InputType == 1:
        match1Clip = Deinterlace
    else:
        match1Clip = Weave(core.std.SelectEvery(core.std.SeparateFields(Deinterlace, TFF), 4, [0, 3]), TFF)
    if SourceMatch < 1 or MatchTR1 <= 0:
        match1Update = Source
    else:
        match1Update = core.std.Expr([Source, match1Clip], ['x {} * y {} * -'.format(errorAdjust1 + 1, errorAdjust1)])
    if SourceMatch > 0:
        match1Edi = QTGMC_Interpolate(match1Update, InputType, MatchEdi, MatchNNSize, MatchNNeurons, MatchEdiQual, MatchEdiMaxD, TFF=TFF)
        if MatchTR1 > 0:
            match1Super = core.mv.Super(match1Edi, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
            match1Degrain1 = core.mv.Degrain1(match1Edi, match1Super, bVec1, fVec1, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
        if MatchTR1 > 1:
            match1Degrain2 = core.mv.Degrain1(match1Edi, match1Super, bVec2, fVec2, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
    if SourceMatch < 1:
        match1 = Deinterlace
    elif MatchTR1 <= 0:
        match1 = match1Edi
    elif MatchTR1 == 1:
        match1 = core.std.Merge(match1Degrain1, match1Edi, weight=[0.25])
    else:
        match1 = core.std.Merge(core.std.Merge(match1Degrain1, match1Degrain2, weight=[0.2]), match1Edi, weight=[0.0625])
    if SourceMatch < 2:
        return match1
    
    # Enhance effect of source-match stages 2 & 3 by sharpening clip prior to refinement (source-match tends to underestimate so this will leave result sharper)
    if SourceMatch > 1 and MatchEnhance > 0:
        match1Shp = core.std.Expr([match1, core.rgvs.RemoveGrain(match1, 12)], ['x x y - {MatchEnhance} * +'.format(MatchEnhance=MatchEnhance)])
    else:
        match1Shp = match1
    
    # Source-match refinement. Find difference between source clip & equivalent fields in (updated) interpolated/smoothed clip. Interpolate & binomially smooth
    # this difference then add it back to output. Helps restore differences that the basic match missed. However, as this pass works on a difference rather than
    # the source image it can be prone to occasional artefacts (difference images are not ideal for interpolation). In fact a lower quality interpolation such
    # as a simple bob often performs nearly as well as advanced, slower methods (e.g. NNEDI3)
    if SourceMatch < 2 or InputType == 1:
        match2Clip = match1Shp
    else:
        match2Clip = Weave(core.std.SelectEvery(core.std.SeparateFields(match1Shp, TFF), 4, [0, 3]), TFF)
    if SourceMatch > 1:
        match2Diff = core.std.MakeDiff(Source, match2Clip)
        match2Edi = QTGMC_Interpolate(match2Diff, InputType, MatchEdi2, MatchNNSize2, MatchNNeurons2, MatchEdiQual2, MatchEdiMaxD2, TFF=TFF)
        if MatchTR2 > 0:
            match2Super = core.mv.Super(match2Edi, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
            match2Degrain1 = core.mv.Degrain1(match2Edi, match2Super, bVec1, fVec1, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
        if MatchTR2 > 1:
            match2Degrain2 = core.mv.Degrain1(match2Edi, match2Super, bVec2, fVec2, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
    if SourceMatch < 2:
        match2 = match1
    elif MatchTR2 <= 0:
        match2 = match2Edi
    elif MatchTR2 == 1:
        match2 = core.std.Merge(match2Degrain1, match2Edi, weight=[0.25])
    else:
        match2 = core.std.Merge(core.std.Merge(match2Degrain1, match2Degrain2, weight=[0.2]), match2Edi, weight=[0.0625])
    
    # Source-match second refinement - correct error introduced in the refined difference by temporal smoothing. Similar to error correction from basic step
    errorAdjust2 = [1, 2/(1+errorTemporalSimilarity), 8/(3+5*errorTemporalSimilarity)][MatchTR2]
    if SourceMatch < 3 or MatchTR2 <= 0:
        match3Update = match2Edi
    else:
        match3Update = core.std.Expr([match2Edi, match2], ['x {} * y {} * -'.format(errorAdjust2 + 1, errorAdjust2)])
    if SourceMatch > 2:
        if MatchTR2 > 0:
            match3Super = core.mv.Super(match3Update, pel=SubPel, sharp=SubPelInterp, levels=1, hpad=hpad, vpad=vpad)
            match3Degrain1 = core.mv.Degrain1(match3Update, match3Super, bVec1, fVec1, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
        if MatchTR2 > 1:
            match3Degrain2 = core.mv.Degrain1(match3Update, match3Super, bVec2, fVec2, thsad=ThSAD1, thscd1=ThSCD1, thscd2=ThSCD2)
    if SourceMatch < 3:
        match3 = match2
    elif MatchTR2 <= 0:
        match3 = match3Update
    elif MatchTR2 == 1:
        match3 = core.std.Merge(match3Degrain1, match3Update, weight=[0.25])
    else:
        match3 = core.std.Merge(core.std.Merge(match3Degrain1, match3Degrain2, weight=[0.2]), match3Update, weight=[0.0625])
    
    # Apply difference calculated in source-match refinement
    return core.std.MergeDiff(match1Shp, match3)


# ivtc_txt60mc v1.1 by cretindesalpes (http://forum.doom9.org/showthread.php?p=1466105#post1466105)
def ivtc_txt60mc(src, frame_ref, srcbob=False, draft=False, tff=None):
    core = vs.get_core()
    
    if not isinstance(src, vs.VideoNode) or src.format.id not in [vs.YUV420P8, vs.YUV422P8]:
        raise ValueError('ivtc_txt60mc: This is not a YUV420P8/YUV422P8 clip !')
    if not (srcbob or isinstance(tff, bool)):
        raise ValueError("ivtc_txt60mc: 'tff' must be set if srcbob is not true. Setting tff to true means top field first and false means bottom field first")
    
    field_ref = frame_ref if srcbob else frame_ref * 2
    field_ref %= 5
    invpos = (5 - field_ref) % 5
    pel = 1 if draft else 2
    blksize = 16 if src.width >= 1280 or src.height >= 720 else 8
    overlap = int(blksize / 2)
    
    if srcbob:
        last = src
    elif draft:
        last = Bob(src, tff=tff)
    else:
        last = QTGMC(src, TR0=1, TR1=1, TR2=1, SourceMatch=3, Lossless=2, TFF=tff)
    
    if invpos > 1:
        clean = core.std.AssumeFPS(core.std.Trim(last, 0, 0)+core.std.SelectEvery(last, 5, [6-invpos]), fpsnum=12000, fpsden=1001)
    else:
        clean = core.std.SelectEvery(last, 5, [1-invpos])
    if invpos > 3:
        jitter = core.std.AssumeFPS(core.std.Trim(last, 0, 0)+core.std.SelectEvery(last, 5, [4-invpos, 8-invpos]), fpsnum=24000, fpsden=1001)
    else:
        jitter = core.std.SelectEvery(last, 5, [3-invpos, 4-invpos])
    jsup = core.mv.Super(jitter, pel=pel)
    vect_f = core.mv.Analyse(jsup, blksize=blksize, isb=False, delta=1, overlap=overlap)
    vect_b = core.mv.Analyse(jsup, blksize=blksize, isb=True, delta=1, overlap=overlap)
    comp = core.mv.FlowInter(jitter, jsup, vect_b, vect_f)
    fixed = core.std.SelectEvery(comp, 2, [0])
    last = core.std.Interleave([clean, fixed])
    return core.std.AssumeFPS(core.std.Trim(last, int(invpos/2)), fpsnum=24000, fpsden=1001)


# Vinverse: a small, but effective Function against (residual) combing, by Didée
# sstr  : strength of contra sharpening
# amnt  : change no pixel by more than this (default=255: unrestricted)
# chroma: chroma mode, True=process chroma, False=pass chroma through
def Vinverse(clp, sstr=2.7, amnt=255, chroma=True):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode):
        raise ValueError('Vinverse: This is not a clip !')
    
    if clp.format.num_planes == 1:
        chroma = False
    planes = [0, 1, 2] if chroma else [0]
    
    # x 128 - y 128 - * 0 < x 128 - abs y 128 - abs < x y ? 128 - 0.25 * 128 + x 128 - abs y 128 - abs < x y ? ?
    def get_lut1(x, y):
        tmp = x if abs(x - 128) < abs(y - 128) else y
        if (x - 128) * (y - 128) < 0:
            return round((tmp - 128) * 0.25 + 128)
        else:
            return tmp
    # x AMN + y < x AMN + x AMN - y > x AMN - y ? ?
    def get_lut2(x, y):
        if x + amnt < y:
            return x + amnt
        elif x - amnt > y:
            return x - amnt
        else:
            return y
    
    if not chroma and clp.format.num_planes == 3:
        clp_src = clp
        clp = core.std.ShufflePlanes(clp, planes=[0], colorfamily=vs.GRAY)
    else:
        clp_src = None
    
    vblur = core.generic.Convolution(clp, [50, 99, 50], mode='v', planes=planes)
    vblurD = core.std.MakeDiff(clp, vblur, planes=planes)
    vshrp = core.std.Expr([vblur, core.generic.Convolution(vblur, [1, 4, 6, 4, 1], mode='v', planes=planes)], ['x x y - {STR} * +'.format(STR=sstr)])
    vshrpD = core.std.MakeDiff(vshrp, vblur, planes=planes)
    if clp.format.bits_per_sample > 8:
        expr = 'x {median} - y {median} - * 0 < x {median} - abs y {median} - abs < x y ? {median} - 0.25 * {median} + x {median} - abs y {median} - abs < x y ? ?'.format(median=1<<(clp.format.bits_per_sample-1))
        vlimD = core.std.Expr([vshrpD, vblurD], [expr])
    else:
        vlimD = core.std.Lut2(vshrpD, vblurD, planes=planes, function=get_lut1)
    last = core.std.MergeDiff(vblur, vlimD, planes=planes)
    if amnt <= 0:
        return clp
    elif amnt < 255:
        if clp.format.bits_per_sample > 8:
            last = core.std.Expr([clp, last], ['x {AMN} + y < x {AMN} + x {AMN} - y > x {AMN} - y ? ?'.format(AMN=amnt<<(clp.format.bits_per_sample-8))])
        else:
            last = core.std.Lut2(clp, last, planes=planes, function=get_lut2)
    
    if not chroma and clp_src is not None:
        return core.std.ShufflePlanes([last, clp_src], planes=[0, 1, 2], colorfamily=clp_src.format.color_family)
    else:
        return last


def Vinverse2(clp, sstr=2.7, amnt=255, chroma=True):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode):
        raise ValueError('Vinverse2: This is not a clip !')
    
    if clp.format.num_planes == 1:
        chroma = False
    planes = [0, 1, 2] if chroma else [0]
    
    # x 128 - y 128 - * 0 < x 128 - abs y 128 - abs < x y ? 128 - 0.25 * 128 + x 128 - abs y 128 - abs < x y ? ?
    def get_lut1(x, y):
        tmp = x if abs(x - 128) < abs(y - 128) else y
        if (x - 128) * (y - 128) < 0:
            return round((tmp - 128) * 0.25 + 128)
        else:
            return tmp
    # x AMN + y < x AMN + x AMN - y > x AMN - y ? ?
    def get_lut2(x, y):
        if x + amnt < y:
            return x + amnt
        elif x - amnt > y:
            return x - amnt
        else:
            return y
    
    if not chroma and clp.format.num_planes == 3:
        clp_src = clp
        clp = core.std.ShufflePlanes(clp, planes=[0], colorfamily=vs.GRAY)
    else:
        clp_src = None
    
    vblur = sbrV(clp, planes=planes)
    vblurD = core.std.MakeDiff(clp, vblur, planes=planes)
    vshrp = core.std.Expr([vblur, core.generic.Convolution(vblur, [1, 2, 1], mode='v', planes=planes)], ['x x y - {STR} * +'.format(STR=sstr)])
    vshrpD = core.std.MakeDiff(vshrp, vblur, planes=planes)
    if clp.format.bits_per_sample > 8:
        expr = 'x {median} - y {median} - * 0 < x {median} - abs y {median} - abs < x y ? {median} - 0.25 * {median} + x {median} - abs y {median} - abs < x y ? ?'.format(median=1<<(clp.format.bits_per_sample-1))
        vlimD = core.std.Expr([vshrpD, vblurD], [expr])
    else:
        vlimD = core.std.Lut2(vshrpD, vblurD, planes=planes, function=get_lut1)
    last = core.std.MergeDiff(vblur, vlimD, planes=planes)
    if amnt <= 0:
        return clp
    elif amnt < 255:
        if clp.format.bits_per_sample > 8:
            last = core.std.Expr([clp, last], ['x {AMN} + y < x {AMN} + x {AMN} - y > x {AMN} - y ? ?'.format(AMN=amnt<<(clp.format.bits_per_sample-8))])
        else:
            last = core.std.Lut2(clp, last, planes=planes, function=get_lut2)
    
    if not chroma and clp_src is not None:
        return core.std.ShufflePlanes([last, clp_src], planes=[0, 1, 2], colorfamily=clp_src.format.color_family)
    else:
        return last


########################################################
#                                                      #
# LUTDeCrawl, a dot crawl removal script by Scintilla  #
# Created 10/3/08                                      #
# Last updated 10/3/08                                 #
#                                                      #
########################################################
#
# Requires YUV input, frame-based only.
# Is of average speed (faster than VagueDenoiser, slower than HQDN3D).
# Suggestions for improvement welcome: scintilla@aquilinestudios.org
#
# Arguments:
#
# ythresh (default=10) - This determines how close the luma values of the
#	pixel in the previous and next frames have to be for the pixel to
#	be hit.  Higher values (within reason) should catch more dot crawl,
#	but may introduce unwanted artifacts.  Probably shouldn't be set
#	above 20 or so. [int]
#
# cthresh (default=10) - This determines how close the chroma values of the
#	pixel in the previous and next frames have to be for the pixel to
#	be hit.  Just as with ythresh. [int]
#
# maxdiff (default=50) - This is the maximum difference allowed between the
#	luma values of the pixel in the CURRENT frame and in each of its
#	neighbour frames (so, the upper limit to what fluctuations are
#	considered dot crawl).  Lower values will reduce artifacts but may
#	cause the filter to miss some dot crawl.  Obviously, this should
#	never be lower than ythresh.  Meaningless if usemaxdiff = false. [int]
#
# scnchg (default=25) - Scene change detection threshold.  Any frame with
#	total luma difference between it and the previous/next frame greater
#	than this value will not be processed. [int]
#
# usemaxdiff (default=true) - Whether or not to reject luma fluctuations
#	higher than maxdiff.  Setting this to false is not recommended, as
#	it may introduce artifacts; but on the other hand, it produces a
#	30% speed boost.  Test on your particular source. [bool]
#
# mask (default=false) - When set true, the function will return the mask
#	instead of the image.  Use to find the best values of cthresh,
#	ythresh, and maxdiff. [bool]
#	(The scene change threshold, scnchg, is not reflected in the mask.)
#
###################
#
# Changelog:
#
# 10/3/08: Is this thing on?
#
###################
def LUTDeCrawl(input, ythresh=10, cthresh=15, maxdiff=50, scnchg=25, usemaxdiff=True, mask=False):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode) or input.format.color_family != vs.YUV or input.format.bits_per_sample > 10:
        raise ValueError('LUTDeCrawl: This is not an 8-10 bits YUV clip !')
    
    shift = input.format.bits_per_sample - 8
    peak = (1 << input.format.bits_per_sample) - 1
    
    ythresh <<= shift
    cthresh <<= shift
    maxdiff <<= shift
    scnchg <<= shift
    
    input_minus = core.std.Trim(input, 0, 0) + input
    input_plus = core.std.Trim(input, 1) + core.std.Trim(input, input.num_frames-1)
    
    input_y = core.std.ShufflePlanes(input, planes=[0], colorfamily=vs.GRAY)
    input_minus_y = core.std.ShufflePlanes(input_minus, planes=[0], colorfamily=vs.GRAY)
    input_minus_u = core.std.ShufflePlanes(input_minus, planes=[1], colorfamily=vs.GRAY)
    input_minus_v = core.std.ShufflePlanes(input_minus, planes=[2], colorfamily=vs.GRAY)
    input_plus_y = core.std.ShufflePlanes(input_plus, planes=[0], colorfamily=vs.GRAY)
    input_plus_u = core.std.ShufflePlanes(input_plus, planes=[1], colorfamily=vs.GRAY)
    input_plus_v = core.std.ShufflePlanes(input_plus, planes=[2], colorfamily=vs.GRAY)
    
    average_y = core.std.Expr([input_minus_y, input_plus_y], ['x y - abs {ythr} < x y + 2 / 0 ?'.format(ythr=ythresh)])
    average_u = core.std.Expr([input_minus_u, input_plus_u], ['x y - abs {cthr} < {peak} 0 ?'.format(cthr=cthresh, peak=peak)])
    average_v = core.std.Expr([input_minus_v, input_plus_v], ['x y - abs {cthr} < {peak} 0 ?'.format(cthr=cthresh, peak=peak)])
    
    ymask = core.generic.Binarize(average_y, threshold=1<<shift)
    if usemaxdiff:
        diffplus_y = core.std.Expr([input_plus_y, input_y], ['x y - abs {md} < {peak} 0 ?'.format(md=maxdiff, peak=peak)])
        diffminus_y = core.std.Expr([input_minus_y, input_y], ['x y - abs {md} < {peak} 0 ?'.format(md=maxdiff, peak=peak)])
        diffs_y = core.std.Lut2(diffplus_y, diffminus_y, function=lambda x, y: x & y)
        ymask = core.std.Lut2(ymask, diffs_y, function=lambda x, y: x & y)
    cmask = core.std.Lut2(core.generic.Binarize(average_u, threshold=129<<shift), core.generic.Binarize(average_v, threshold=129<<shift),
                          function=lambda x, y: x & y)
    cmask = Resize(cmask, input.width, input.height, kernel='point')
    
    themask = core.std.Lut2(ymask, cmask, function=lambda x, y: x & y)
    
    fixed_y = core.std.Merge(average_y, input_y)
    
    output = core.std.ShufflePlanes([core.std.MaskedMerge(input_y, fixed_y, themask), input], planes=[0, 1, 2], colorfamily=input.format.color_family)
    
    def YDifferenceFromPrevious(n, f, clips):
        if f.props._SceneChangePrev:
            return clips[0]
        else:
            return clips[1]
    def YDifferenceToNext(n, f, clips):
        if f.props._SceneChangeNext:
            return clips[0]
        else:
            return clips[1]
    
    input = core.std.DuplicateFrames(input, [0, input.num_frames-1])
    input = set_scenechange(input, scnchg)
    input = core.std.DeleteFrames(input, [0, input.num_frames-1])
    output = core.std.FrameEval(output, eval=functools.partial(YDifferenceFromPrevious, clips=[input, output]), prop_src=input)
    output = core.std.FrameEval(output, eval=functools.partial(YDifferenceToNext, clips=[input, output]), prop_src=input)
    
    if mask:
        return themask
    else:
        return output


#####################################################
#                                                   #
# LUTDeRainbow, a derainbowing script by Scintilla  #
# Last updated 10/3/08                              #
#                                                   #
#####################################################
#
# Requires YUV input, frame-based only.
# Is of reasonable speed (faster than aWarpSharp, slower than DeGrainMedian).
# Suggestions for improvement welcome: scintilla@aquilinestudios.org
#
# Arguments:
#
# cthresh (default=10) - This determines how close the chroma values of the
#	pixel in the previous and next frames have to be for the pixel to
#	be hit.  Higher values (within reason) should catch more rainbows,
#	but may introduce unwanted artifacts.  Probably shouldn't be set
#	above 20 or so. [int]
#
# ythresh (default=10) - If the y parameter is set true, then this
#	determines how close the luma values of the pixel in the previous
#	and next frames have to be for the pixel to be hit.  Just as with
#	cthresh. [int]
#
# y (default=true) - Determines whether luma difference will be considered
#	in determining which pixels to hit and which to leave alone. [bool]
#
# linkUV (default=true) - Determines whether both chroma channels are
#	considered in determining which pixels in each channel to hit.
#	When set true, only pixels that meet the thresholds for both U and
#	V will be hit; when set false, the U and V channels are masked
#	separately (so a pixel could have its U hit but not its V, or vice
#	versa). [bool]
#
# mask (default=false) - When set true, the function will return the mask
#	(for combined U/V) instead of the image.  Formerly used to find the
#	best values of cthresh and ythresh.  If linkUV=false, then this
#	mask won't actually be used anyway (because each chroma channel
#	will have its own mask). [bool]
#
###################
#
# Changelog:
#
# 6/23/05: Is this thing on?
# 6/24/05: Replaced whole mask mechanism; new mask checks to see that BOTH channels
# 	of the chroma are within the threshold from previous frame to next
# 7/1/05: Added Y option, to take luma into account when deciding whether to use the
#	averaged chroma; added ythresh and cthresh parameters, to determine how close
#	the chroma/luma values of a pixel have to be to be considered the same
#	(y=true is meant to cut down on artifacts)
# 9/2/05: Suddenly realized this wouldn't work for YUY2 and made it YV12 only;
#	added linkUV option, to decide whether to use a separate mask for each chroma
#	channel or use the same one for both.
# 10/3/08: Fixed "cthresh" typos in documentation; killed repmode since I realized I
#	wasn't using Repair anymore; finally upgraded to MaskTools 2.
#
###################
def LUTDeRainbow(input, cthresh=10, ythresh=10, y=True, linkUV=True, mask=False):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode) or input.format.color_family != vs.YUV or input.format.bits_per_sample > 10:
        raise ValueError('LUTDeRainbow: This is not an 8-10 bits YUV clip !')
    
    shift = input.format.bits_per_sample - 8
    peak = (1 << input.format.bits_per_sample) - 1
    
    cthresh <<= shift
    ythresh <<= shift
    
    input_minus = core.std.Trim(input, 0, 0) + input
    input_plus = core.std.Trim(input, 1) + core.std.Trim(input, input.num_frames-1)
    
    input_u = core.std.ShufflePlanes(input, planes=[1], colorfamily=vs.GRAY)
    input_v = core.std.ShufflePlanes(input, planes=[2], colorfamily=vs.GRAY)
    input_minus_y = core.std.ShufflePlanes(input_minus, planes=[0], colorfamily=vs.GRAY)
    input_minus_u = core.std.ShufflePlanes(input_minus, planes=[1], colorfamily=vs.GRAY)
    input_minus_v = core.std.ShufflePlanes(input_minus, planes=[2], colorfamily=vs.GRAY)
    input_plus_y = core.std.ShufflePlanes(input_plus, planes=[0], colorfamily=vs.GRAY)
    input_plus_u = core.std.ShufflePlanes(input_plus, planes=[1], colorfamily=vs.GRAY)
    input_plus_v = core.std.ShufflePlanes(input_plus, planes=[2], colorfamily=vs.GRAY)
    
    average_y = Resize(core.std.Expr([input_minus_y, input_plus_y], ['x y - abs {ythr} < {peak} 0 ?'.format(ythr=ythresh, peak=peak)]),
                       int(input.width/2), int(input.height/2), kernel='bilinear')
    average_u = core.std.Expr([input_minus_u, input_plus_u], ['x y - abs {cthr} < x y + 2 / 0 ?'.format(cthr=cthresh)])
    average_v = core.std.Expr([input_minus_v, input_plus_v], ['x y - abs {cthr} < x y + 2 / 0 ?'.format(cthr=cthresh)])
    
    umask = core.generic.Binarize(average_u, threshold=21<<shift)
    vmask = core.generic.Binarize(average_v, threshold=21<<shift)
    themask = core.std.Lut2(umask, vmask, function=lambda x, y: x & y)
    if y:
        umask = core.std.Lut2(umask, average_y, function=lambda x, y: x & y)
        vmask = core.std.Lut2(vmask, average_y, function=lambda x, y: x & y)
        themask = core.std.Lut2(themask, average_y, function=lambda x, y: x & y)
    
    fixed_u = core.std.Merge(average_u, input_u)
    fixed_v = core.std.Merge(average_v, input_v)
    
    output_u = core.std.MaskedMerge(input_u, fixed_u, themask if linkUV else umask)
    output_v = core.std.MaskedMerge(input_v, fixed_v, themask if linkUV else vmask)
    
    output = core.std.ShufflePlanes([input, output_u, output_v], planes=[0, 0, 0], colorfamily=input.format.color_family)
    
    if mask:
        return Resize(themask, input.width, input.height, kernel='point')
    else:
        return output


######
###
### GrainStabilizeMC v1.0      by mawen1250      2014.03.22
###
### Requirements: GenericFilters, MVTools, RemoveGrain/Repair
###
### Temporal-only on-top grain stabilizer
### Only stabilize the difference ( on-top grain ) between source clip and spatial-degrained clip
###
### Parameters:
###  nrmode [int] - Mode to get grain/noise from input clip. 0: 3x3 Average Blur, 1: 3x3 SBR, 2: 5x5 SBR, 3: 7x7 SBR. Or define your own denoised clip "p". Default is 2 for HD / 1 for SD
###  radius [int] - Temporal radius of MDegrain for grain stabilize(1-3). Default is 1
###  adapt [int]  - Threshold for luma-adaptative mask. -1: off, 0: source, 255: invert. Or define your own luma mask clip "Lmask". Default is -1
###  rep [int]    - Mode of repair to avoid artifacts, set 0 to turn off this operation. Default is 13
###  Y,U,V [bool] - If true, the corresponding plane is processed. Otherwise, it is copied through to the output image as is. Default is true,false,false
###
######
def GSMC(input, p=None, Lmask=None, nrmode=None, radius=1, adapt=-1, rep=13, Y=True, U=False, V=False):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode) or input.format.id not in [vs.YUV420P8, vs.YUV422P8]:
        raise ValueError('GSMC: This is not a YUV420P8/YUV422P8 clip !')
    if p is not None and (not isinstance(p, vs.VideoNode) or p.format.id != input.format.id):
        raise ValueError("GSMC: 'p' must be the same format as input !")
    if Lmask is not None and not isinstance(Lmask, vs.VideoNode):
        raise ValueError("GSMC: 'Lmask' is not a clip !")
    
    HD = input.width > 1024 or input.height > 576
    if nrmode is None:
        nrmode = 2 if HD else 1
    
    if Y and U and V:
        planes = [0, 1, 2]
    elif Y and U:
        planes = [0, 1]
    elif Y and V:
        planes = [0, 2]
    elif U and V:
        planes = [1, 2]
    elif Y:
        planes = [0]
    elif U:
        planes = [1]
    elif V:
        planes = [2]
    else:
        return input
    
    chromamv = U or V
    blksize = 32 if HD else 16
    overlap = int(blksize / 4)
    if not Y:
        if not U:
            plane = 2
        elif not V:
            plane = 1
        else:
            plane = 3
    elif not (U or V):
        plane = 0
    else:
        plane = 4
    
    # Kernel: Spatial Noise Dumping
    if p is not None:
        pre_nr = p
    elif nrmode <= 0:
        pre_nr = core.rgvs.RemoveGrain(input, [20 if Y else 0, 20 if U else 0, 20 if V else 0])
    else:
        pre_nr = sbr(input, nrmode, planes=planes)
    dif_nr = core.std.MakeDiff(input, pre_nr, planes=planes)
    
    # Kernel: MC Grain Stabilize
    psuper = core.mv.Super(pre_nr, pel=1, chroma=chromamv)
    difsuper = core.mv.Super(dif_nr, pel=1, levels=1, chroma=chromamv)
    
    fv1 = core.mv.Analyse(psuper, blksize=blksize, isb=False, chroma=chromamv, delta=1, truemotion=False, _global=True, overlap=overlap)
    bv1 = core.mv.Analyse(psuper, blksize=blksize, isb=True, chroma=chromamv, delta=1, truemotion=False, _global=True, overlap=overlap)
    if radius > 1:
        fv2 = core.mv.Analyse(psuper, blksize=blksize, isb=False, chroma=chromamv, delta=2, truemotion=False, _global=True, overlap=overlap)
        bv2 = core.mv.Analyse(psuper, blksize=blksize, isb=True, chroma=chromamv, delta=2, truemotion=False, _global=True, overlap=overlap)
    if radius > 2:
        fv3 = core.mv.Analyse(psuper, blksize=blksize, isb=False, chroma=chromamv, delta=3, truemotion=False, _global=True, overlap=overlap)
        bv3 = core.mv.Analyse(psuper, blksize=blksize, isb=True, chroma=chromamv, delta=3, truemotion=False, _global=True, overlap=overlap)
    
    if radius <= 1:
        dif_sb = core.mv.Degrain1(dif_nr, difsuper, bv1, fv1, thsad=300, thsadc=150, plane=plane, thscd1=300, thscd2=100)
    elif radius == 2:
        dif_sb = core.mv.Degrain2(dif_nr, difsuper, bv1, fv1, bv2, fv2, thsad=300, thsadc=150, plane=plane, thscd1=300, thscd2=100)
    else:
        dif_sb = core.mv.Degrain3(dif_nr, difsuper, bv1, fv1, bv2, fv2, bv3, fv3, thsad=300, thsadc=150, plane=plane, thscd1=300, thscd2=100)
    
    # x adapt - abs 255 * adapt 128 - abs 128 + /
    def get_lut(x):
        return round(abs(x - adapt) * 255 / (abs(adapt - 128) + 128))
    
    # Post-Process: Luma-Adaptive Mask Merging & Repairing
    stable = core.std.MergeDiff(pre_nr, dif_sb, planes=planes)
    if rep > 0:
        stable = core.rgvs.Repair(stable, input, [rep if Y else 0, rep if U else 0, rep if V else 0])
    
    if Lmask is not None:
        return core.std.MaskedMerge(input, stable, Lmask, planes=planes)
    elif adapt <= -1:
        return stable
    else:
        input_y = core.std.ShufflePlanes(input, planes=[0], colorfamily=vs.GRAY)
        if adapt == 0:
            Lmask = core.rgvs.RemoveGrain(input_y, 19)
        elif adapt >= 255:
            Lmask = core.rgvs.RemoveGrain(core.generic.Invert(input_y), 19)
        else:
            Lmask = core.rgvs.RemoveGrain(core.std.Lut(input_y, function=get_lut), 19)
        return core.std.MaskedMerge(input, stable, Lmask, planes=planes)


################################################################################################
###                                                                                          ###
###                           Simple MDegrain Mod - SMDegrain()                              ###
###                                                                                          ###
###                       Mod by Dogway - Original idea by Caroliano                         ###
###                                                                                          ###
###          Special Thanks: Sagekilla, Didée, cretindesalpes, Gavino and MVtools people     ###
###                                                                                          ###
###                       v2.2d (Dogway's mod) - 05 March 2013                               ###
###                                                                                          ###
################################################################################################
###
### General purpose simple degrain function. Pure temporal denoiser. Basically a wrapper(function)/frontend of mvtools2+mdegrain
### with some common related options added. Aim is at accessibility and quality but not targeted to any specific kind of source.
### The reason behind is to keep it simple so aside masktools2 you will only need MVTools2.
###
### Check documentation for deep explanation on settings and defaults.
### Doom10 thread: (http://doom10.org/index.php?topic=2178.0)
###
################################################################################################

# Globals
bv6 = bv4 = bv3 = bv2 = bv1 = fv1 = fv2 = fv3 = fv4 = fv6 = None

def SMDegrain(input, tr=3, thSAD=400, thSADC=None, RefineMotion=False, contrasharp=None, CClip=None, interlaced=False, tff=None, plane=4, Globals=0,
              pel=None, subpixel=2, prefilter=0, blksize=None, overlap=None, search=4, truemotion=None, MVglobal=None, dct=0, limit=255, limitc=None,
              thSCD1=None, thSCD2=130, chroma=True, hpad=None, vpad=None, Str=1., Amp=0.0625):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode) or input.format.id not in [vs.YUV420P8, vs.YUV422P8]:
        raise ValueError('SMDegrain: This is not a YUV420P8/YUV422P8 clip !')
    
    # Defaults & Conditionals
    thSAD2 = int(thSAD / 2)
    if thSADC is None:
        thSADC = thSAD2
    
    GlobalR = Globals == 1
    GlobalO = Globals >= 3
    if1 = CClip is not None
    
    if contrasharp is None:
        contrasharp = not GlobalO and if1
    
    w = input.width
    h = input.height
    preclip = isinstance(prefilter, vs.VideoNode)
    ifC = isinstance(contrasharp, bool)
    if0 = contrasharp if ifC else contrasharp > 0
    if4 = w > 1279 or h > 719
    
    if pel is None:
        pel = 1 if if4 else 2
    pelclip = pel > 1 and subpixel >= 3
    
    if blksize is None:
        blksize = 16 if if4 else 8
    blk2 = int(blksize / 2)
    if overlap is None:
        overlap = blk2
    ovl2 = int(overlap / 2)
    if truemotion is None:
        truemotion = not if4
    if MVglobal is None:
        MVglobal = truemotion
    if thSCD1 is None:
        thSCD1 = int((blksize * 2.5) ** 2)
    
    planes = [0, 1, 2] if chroma else [0]
    plane0 = plane != 0
    
    if hpad is None:
        hpad = 0 if if4 else blksize
    if vpad is None:
        vpad = 0 if if4 else blksize
    if limitc is None:
        limitc = limit
    
    # Error Report
    if not (ifC or isinstance(contrasharp, int)):
        raise ValueError("SMDegrain: 'contrasharp' only accepts bool and integer inputs")
    if if1 and (not isinstance(CClip, vs.VideoNode) or CClip.format.id != input.format.id):
        raise ValueError("SMDegrain: 'CClip' must be the same format as input !")
    if interlaced and h & 3:
        raise ValueError('SMDegrain: Interlaced source requires mod 4 height sizes')
    if interlaced and not isinstance(tff, bool):
        raise ValueError("SMDegrain: 'tff' must be set if source is interlaced. Setting tff to true means top field first and false means bottom field first")
    if not (isinstance(prefilter, int) or preclip):
        raise ValueError("SMDegrain: 'prefilter' only accepts integer and clip inputs")
    if preclip and prefilter.format.id != input.format.id:
        raise ValueError("SMDegrain: 'prefilter' must be the same format as input !")
    if RefineMotion and blksize < 8:
        raise ValueError('SMDegrain: For RefineMotion you need a blksize of at least 8')
    
    # RefineMotion Variables
    if RefineMotion:
        halfblksize = blk2                                          # MRecalculate works with half block size
        halfoverlap = overlap if overlap <= 2 else ovl2 + ovl2 % 2  # Halve the overlap to suit the halved block size
        halfthSAD = thSAD2                                          # MRecalculate uses a more strict thSAD, which defaults to 200 (half of function's default of 400)
    
    # Input preparation for Interlacing
    if not interlaced:
        inputP = input
    else:
        inputP = core.std.SeparateFields(input, tff)
    
    # x 16 < 255 x 75 > 0 255 x 16 - 255 75 16 - / * - ? ?
    def get_lut(x):
        if lsb:
            if x < 4096:
                return 65535
            elif x > 19200:
                return 0
            else:
                return round(65535 - (x - 4096) * (65535 / 15104))
        else:
            if x < 16:
                return 255
            elif x > 75:
                return 0
            else:
                return round(255 - (x - 16) * (255 / 59))
    
    # Prefilter
    if not GlobalR:
        if preclip:
            pref = prefilter
        elif prefilter <= 0:
            pref = inputP
        else:
            pref = MinBlur(inputP, prefilter, planes=planes)
    else:
        pref = inputP
    
    # Default Auto-Prefilter - Luma expansion TV->PC (up to 16% more values for motion estimation)
    if not GlobalR:
        pref = Dither_Luma_Rebuild(pref, s0=Str, c=Amp, chroma=chroma)
    
    # Subpixel 3
    if pelclip:
        pclip = core.nnedi3.nnedi3_rpow2(pref, rfactor=pel, nns=4, qual=2)
        if not GlobalR:
            pclip2 = core.nnedi3.nnedi3_rpow2(inputP, rfactor=pel, nns=4, qual=2)
    
    # Motion vectors search
    global bv6, bv4, bv3, bv2, bv1, fv1, fv2, fv3, fv4, fv6
    if pelclip:
        super_search = core.mv.Super(pref, pel=pel, chroma=chroma, hpad=hpad, vpad=vpad, pelclip=pclip, rfilter=4)
    else:
        super_search = core.mv.Super(pref, pel=pel, sharp=subpixel, chroma=chroma, hpad=hpad, vpad=vpad, rfilter=4)
    if not GlobalR:
        if pelclip:
            super_render = core.mv.Super(inputP, pel=pel, chroma=plane0, hpad=hpad, vpad=vpad, levels=1, pelclip=pclip2)
            if RefineMotion:
                Recalculate = core.mv.Super(pref, pel=pel, chroma=chroma, hpad=hpad, vpad=vpad, levels=1, pelclip=pclip)
        else:
            super_render = core.mv.Super(inputP, pel=pel, sharp=subpixel, chroma=plane0, hpad=hpad, vpad=vpad, levels=1)
            if RefineMotion:
                Recalculate = core.mv.Super(pref, pel=pel, sharp=subpixel, chroma=chroma, hpad=hpad, vpad=vpad, levels=1)
        if interlaced:
            if tr > 2:
                bv6 = core.mv.Analyse(super_search, isb=True, delta=6, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                fv6 = core.mv.Analyse(super_search, isb=False, delta=6, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                if RefineMotion:
                    bv6 = core.mv.Recalculate(Recalculate, bv6, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
                    fv6 = core.mv.Recalculate(Recalculate, fv6, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
            if tr > 1:
                bv4 = core.mv.Analyse(super_search, isb=True, delta=4, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                fv4 = core.mv.Analyse(super_search, isb=False, delta=4, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                if RefineMotion:
                    bv4 = core.mv.Recalculate(Recalculate, bv4, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
                    fv4 = core.mv.Recalculate(Recalculate, fv4, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
        else:
            if tr > 2:
                bv3 = core.mv.Analyse(super_search, isb=True, delta=3, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                fv3 = core.mv.Analyse(super_search, isb=False, delta=3, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                      truemotion=truemotion, _global=MVglobal, dct=dct)
                if RefineMotion:
                    bv3 = core.mv.Recalculate(Recalculate, bv3, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
                    fv3 = core.mv.Recalculate(Recalculate, fv3, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
            bv1 = core.mv.Analyse(super_search, isb=True, delta=1, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                  truemotion=truemotion, _global=MVglobal, dct=dct)
            fv1 = core.mv.Analyse(super_search, isb=False, delta=1, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                  truemotion=truemotion, _global=MVglobal, dct=dct)
            if RefineMotion:
                bv1 = core.mv.Recalculate(Recalculate, bv1, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
                fv1 = core.mv.Recalculate(Recalculate, fv1, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
        if interlaced or tr > 1:
            bv2 = core.mv.Analyse(super_search, isb=True, delta=2, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                  truemotion=truemotion, _global=MVglobal, dct=dct)
            fv2 = core.mv.Analyse(super_search, isb=False, delta=2, overlap=overlap, blksize=blksize, search=search, chroma=chroma,
                                  truemotion=truemotion, _global=MVglobal, dct=dct)
            if RefineMotion:
                bv2 = core.mv.Recalculate(Recalculate, bv2, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
                fv2 = core.mv.Recalculate(Recalculate, fv2, overlap=halfoverlap, blksize=halfblksize, thsad=halfthSAD, chroma=chroma, truemotion=truemotion)
    else:
        super_render = super_search
    
    # Finally, MDegrain
    if not GlobalO:
        if interlaced:
            if tr >= 3:
                output = core.mv.Degrain3(inputP, super_render, bv2, fv2, bv4, fv4, bv6, fv6, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
            elif tr == 2:
                output = core.mv.Degrain2(inputP, super_render, bv2, fv2, bv4, fv4, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
            else:
                output = core.mv.Degrain1(inputP, super_render, bv2, fv2, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
        else:
            if tr >= 3:
                output = core.mv.Degrain3(inputP, super_render, bv1, fv1, bv2, fv2, bv3, fv3, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
            elif tr == 2:
                output = core.mv.Degrain2(inputP, super_render, bv1, fv1, bv2, fv2, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
            else:
                output = core.mv.Degrain1(inputP, super_render, bv1, fv1, thsad=thSAD, thsadc=thSADC, thscd1=thSCD1, thscd2=thSCD2,
                                          limit=limit, limitc=limitc, plane=plane)
    
    # Contrasharp (only sharpens luma)
    if not GlobalO and if0:
        if if1:
            if interlaced:
                CClip = core.std.SeparateFields(CClip, tff)
        else:
            CClip = inputP
    
    # Output
    if not GlobalO:
        if if0:
            if interlaced:
                if ifC:
                    return Weave(ContraSharpening(output, CClip), tff)
                else:
                    return Weave(LSFmod(output, strength=contrasharp, source=CClip, Lmode=0, soft=0, soothe=False, defaults='slow'), tff)
            elif ifC:
                return ContraSharpening(output, CClip)
            else:
                return LSFmod(output, strength=contrasharp, source=CClip, Lmode=0, soft=0, soothe=False, defaults='slow')
        elif interlaced:
            return Weave(output, tff)
        else:
            return output
    else:
        return input


##############################
# FastLineDarken 1.4x MT MOD #
##############################
#
# Written by Vectrangle    (http://forum.doom9.org/showthread.php?t=82125)
# Didée: - Speed Boost, Updated: 11th May 2007
# Dogway - added protection option. 12-May-2011
#
# Parameters are:
#  strength (integer)   - Line darkening amount, 0-256. Default 48. Represents the _maximum_ amount
#                         that the luma will be reduced by, weaker lines will be reduced by
#                         proportionately less.
#  protection (integer) - Prevents the darkest lines from being darkened. Protection acts as a threshold.
#                         Values range from 0 (no prot) to ~50 (protect everything)
#  luma_cap (integer)   - value from 0 (black) to 255 (white), used to stop the darkening
#                         determination from being 'blinded' by bright pixels, and to stop grey
#                         lines on white backgrounds being darkened. Any pixels brighter than
#                         luma_cap are treated as only being as bright as luma_cap. Lowering
#                         luma_cap tends to reduce line darkening. 255 disables capping. Default 191.
#  threshold (integer)  - any pixels that were going to be darkened by an amount less than
#                         threshold will not be touched. setting this to 0 will disable it, setting
#                         it to 4 (default) is recommended, since often a lot of random pixels are
#                         marked for very slight darkening and a threshold of about 4 should fix
#                         them. Note if you set threshold too high, some lines will not be darkened
#  thinning (integer)   - optional line thinning amount, 0-256. Setting this to 0 will disable it,
#                         which is gives a _big_ speed increase. Note that thinning the lines will
#                         inherently darken the remaining pixels in each line a little. Default 0.
#
# Changelog:
#  1.4  - added protection option. Prevents darkest lines to be over darkened thus creating artifacts (i.e. aliasing, clipping...)
#       - Optmized the code as suggested by Didée for possible faster processing. It also deals with the green screen bug.
#  1.3  - added ability to thin lines, now runs much slower unless thinning=0. Changed the defaults (again)
#  1.2  - huge speed increase using yv12lutxy =)
#       - weird darkening issues gone (they were caused by yv12layer)
#       - show option no longer available due to optimizations. Use subtract() instead
#  1.1  - added luma_cap option
#  1.0  - initial release
def FastLineDarkenMOD(c, strength=48, protection=5, luma_cap=191, threshold=4, thinning=0):
    core = vs.get_core()
    
    if not isinstance(c, vs.VideoNode):
        raise ValueError('FastLineDarkenMOD: This is not a clip !')
    
    shift = c.format.bits_per_sample - 8
    peak = (1 << c.format.bits_per_sample) - 1
    
    Str = strength / 128
    lum = peak if luma_cap >= 255 else luma_cap << shift
    thr = threshold << shift
    thn = thinning / 16
    
    if c.format.num_planes == 3:
        c_src = c
        c = core.std.ShufflePlanes(c, planes=[0], colorfamily=vs.GRAY)
    else:
        c_src = None
    
    exin = core.generic.Minimum(core.generic.Maximum(c, threshold=int(peak/(protection+1))))
    thick = core.std.Expr([c, exin], ['y {lum} < y {lum} ? x {thr} + > x y {lum} < y {lum} ? - 0 ? {Str} * x +'.format(lum=lum, thr=thr, Str=Str)])
    
    if thinning <= 0:
        last = thick
    else:
        diff = core.std.Expr([c, exin], ['y {lum} < y {lum} ? x {thr} + > x y {lum} < y {lum} ? - 0 ? {i} +'.format(lum=lum, thr=thr, i=127<<shift)])
        linemask = core.rgvs.RemoveGrain(core.std.Expr([core.generic.Minimum(diff)], ['x {i} - {thn} * {j} +'.format(thn=thn, i=127<<shift, j=255<<shift)]), 20)
        thin = core.std.Expr([core.generic.Maximum(c), diff], ['x y {i} - {Str} 1 + * +'.format(Str=Str, i=127<<shift)])
        last = core.std.MaskedMerge(thin, thick, linemask)
    
    if c_src is not None:
        return core.std.ShufflePlanes([last, c_src], planes=[0, 1, 2], colorfamily=c_src.format.color_family)
    else:
        return last


def Resize(src, w, h, sx=0., sy=0., sw=0., sh=0., kernel='spline36', taps=4, a1=None, a2=None, css=None, planes=[3, 3, 3], cplace='mpeg2',
           cplaces=None, cplaced=None, interlaced=2, interlacedd=2, flt=False, noring=False, bits=None, fulls=None, fulld=None, dmode=3, ampo=1., ampn=0.):
    core = vs.get_core()
    
    if not isinstance(src, vs.VideoNode):
        raise ValueError('Resize: This is not a clip !')
    
    kernel = kernel.lower()
    if bits is None:
        bits = src.format.bits_per_sample
    
    sr_h = w / src.width
    sr_v = h / src.height
    sr_up = max(sr_h, sr_v)
    sr_dw = 1 / min(sr_h, sr_v)
    sr = max(sr_up, sr_dw)
    assert(sr >= 1)
    
    # Depending on the scale ratio, we may blend or totally disable the ringing cancellation
    thr = 2.5
    nrb = sr > thr
    nrf = sr < thr + 1 and noring
    if nrb:
        nrr = min(sr - thr, 1)
        nrv = round((1 - nrr) * 255)
        nrv = nrv * 256 + nrv
    
    if kernel in ['cubic', 'bicubic']:
        if a1 is None:
            a1 = 1 / 3
        if a2 is None:
            a2 = 1 / 3
    elif kernel in ['gauss', 'gaussian']:
        if a1 is None:
            a1 = 30
    main = core.fmtc.resample(src, w, h, sx, sy, sw, sh, kernel=kernel, taps=taps, a1=a1, a2=a2, css=css, planes=planes, cplace=cplace,
                              cplaces=cplaces, cplaced=cplaced, interlaced=interlaced, interlacedd=interlacedd, flt=flt)
    
    if nrf:
        nrng = core.fmtc.resample(src, w, h, sx, sy, sw, sh, kernel='gauss', taps=taps, a1=100, css=css, planes=planes, cplace=cplace,
                                  cplaces=cplaces, cplaced=cplaced, interlaced=interlaced, interlacedd=interlacedd, flt=flt)
        
        # To do: use a simple frame blending instead of Merge
        last = core.rgvs.Repair(main, nrng, 1)
        if nrb:
            nrm = core.std.BlankClip(main, color=[nrv] if main.format.num_planes==1 else [nrv, nrv, nrv])
            last = core.std.MaskedMerge(main, last, nrm)
    else:
        last = main
    
    if bits < 16:
        return core.fmtc.bitdepth(last, bits=bits, fulls=fulls, fulld=fulld, dmode=dmode, ampo=ampo, ampn=ampn)
    else:
        return last


# Converts the luma channel to linear light
def GammaToLinear(src, fulls=True, fulld=True, curve='709', planes=[0, 1, 2], gcor=1., sigmoid=False, thr=0.5, cont=6.5):
    if not isinstance(src, vs.VideoNode) or src.format.bits_per_sample != 16:
        raise ValueError('GammaToLinear: This is not a 16-bit clip !')
    
    return LinearAndGamma(src, False, fulls, fulld, curve.lower(), planes, gcor, sigmoid, thr, cont)

# Converts back a clip to gamma-corrected luma
def LinearToGamma(src, fulls=True, fulld=True, curve='709', planes=[0, 1, 2], gcor=1., sigmoid=False, thr=0.5, cont=6.5):
    if not isinstance(src, vs.VideoNode) or src.format.bits_per_sample != 16:
        raise ValueError('LinearToGamma: This is not a 16-bit clip !')
    
    return LinearAndGamma(src, True, fulls, fulld, curve.lower(), planes, gcor, sigmoid, thr, cont)

def LinearAndGamma(src, l2g_flag, fulls, fulld, curve, planes, gcor, sigmoid, thr, cont):
    core = vs.get_core()
    
    if curve == 'srgb':
        c_num = 0
    elif curve in ['709', '601', '170']:
        c_num = 1
    elif curve == '240':
        c_num = 2
    elif curve == '2020':
        c_num = 3
    else:
        raise ValueError('LinearAndGamma: wrong curve value.')
    
    if src.format.num_planes == 1:
        planes = [0]
    
    #                 BT-709/601
    #        sRGB     SMPTE 170M   SMPTE 240M   BT-2020
    k0    = [0.04045, 0.081,       0.0912,      0.08145][c_num]
    phi   = [12.92,   4.5,         4.0,         4.5][c_num]
    alpha = [0.055,   0.099,       0.1115,      0.0993][c_num]
    gamma = [2.4,     2.22222,     2.22222,     2.22222][c_num]
    
    def g2l(x):
        expr = x / 65536 if fulls else (x - 4096) / 56064
        if expr <= k0:
            expr /= phi
        else:
            expr = ((expr + alpha) / (1 + alpha)) ** gamma
        if gcor != 1 and expr >= 0:
            expr **= gcor
        if sigmoid:
            x0 = 1 / (1 + math.exp(cont * thr))
            x1 = 1 / (1 + math.exp(cont * (thr - 1)))
            expr = thr - math.log(max(1 / max(expr * (x1 - x0) + x0, 0.000001) - 1, 0.000001)) / cont
        if fulld:
            return min(max(round(expr * 65536), 0), 65535)
        else:
            return min(max(round(expr * 56064 + 4096), 0), 65535)
    
    # E' = (E <= k0 / phi)   ?   E * phi   :   (E ^ (1 / gamma)) * (alpha + 1) - alpha
    def l2g(x):
        expr = x / 65536 if fulls else (x - 4096) / 56064
        if sigmoid:
            x0 = 1 / (1 + math.exp(cont * thr))
            x1 = 1 / (1 + math.exp(cont * (thr - 1)))
            expr = (1 / (1 + math.exp(cont * (thr - expr))) - x0) / (x1 - x0)
        if gcor != 1 and expr >= 0:
            expr **= gcor
        if expr <= k0 / phi:
            expr *= phi
        else:
            expr = expr ** (1 / gamma) * (alpha + 1) - alpha
        if fulld:
            return min(max(round(expr * 65536), 0), 65535)
        else:
            return min(max(round(expr * 56064 + 4096), 0), 65535)
    
    return core.std.Lut(src, planes=planes, function=l2g if l2g_flag else g2l)


################################################################################################
###                                                                                          ###
###                       LimitedSharpenFaster MOD : function LSFmod()                       ###
###                                                                                          ###
###                                Modded Version by LaTo INV.                               ###
###                                                                                          ###
###                                  v1.9 - 05 October 2009                                  ###
###                                                                                          ###
################################################################################################
###
### +-----------+
### | CHANGELOG |
### +-----------+
###
### v1.9 : - tweaked settings
###        - default preset is now defaults="fast" /!\
###
### v1.8 : - changed preblur to allow more tweaking (bool->string)
###        - tweaked settings
###        - cleaned the code
###        - updated documentation
###
### v1.7 : - changed Smethod=4 to "source"
###
### v1.6 : - added preblur option
###        - added new Smethod=4
###
### v1.5 : - fixed LUT expression (thanks to Didée)
###        - changed Smethod to Smethod+secure
###
### v1.4 : - changed defaults="new" to defaults="slow" & defaults="fast"
###        - added show parameter
###        - cleaned a little the code
###
### v1.3 : - changed a little Smethod=3&5 (same effect, but more precise)
###        - added new calculation for soft (soft=-2) [default on]
###        - added warning about bad settings (no more silent)
###        - updated the documentation
###
### v1.2 : - added new Lmode<0 (limit with repair)
###        - added 2 new Smode (unsharp masking)
###        - changed Smode order: now old Smode3-4 is new Smode3-4 to avoid mistake
###
### v1.1 : - fixed a bug with dest_x!=ox or dest_y!=oy
###        - replaced Lfactor by over/undershoot2
###
### v1.0 : - deleted old Smode(1-4), added new Smode(1-3) & Smethod(1-5)
###        - added parameters for nonlinear sharpening (S2zp,S2pwr,S2dmpLo,S2dmpHi)
###        - corrected the nonlinear formula
###        - added new Lmode 2 & 4 + fixed Lmode 0
###        - added faster edgemask
###        - added soothe temporal stabilization, 2 parameters: soothe & keep
###        - replaced lanczosresize by spline36resize
###        - moved "strength" parameter (first place)
###        - deleted wide, special and exborder
###        - changed some code (cosmetic)
###        - added "defaults" parameter (to switch between original and modded version)
###        - added documentation
###
###
###
### +--------------+
### | DEPENDENCIES |
### +--------------+
###
### -> GenericFilters
### -> RemoveGrain/Repair
###
###
###
### +---------+
### | GENERAL |
### +---------+
###
### strength [int]
### --------------
### Strength of the sharpening
###
### Smode [int: 1,2]
### ----------------------
### Sharpen mode:
###    =1 : Range sharpening
###    =2 : Nonlinear sharpening (corrected version)
###
### Smethod [int: 1,2,3]
### --------------------
### Sharpen method:
###    =1 : 3x3 kernel
###    =2 : Min/Max
###    =3 : Min/Max + 3x3 kernel
###
### kernel [int: 11,12,19,20]
### -------------------------
### Kernel used in Smethod=1&3
### In strength order: + 19 > 12 >> 20 > 11 -
###
###
###
### +---------+
### | SPECIAL |
### +---------+
###
### preblur [bool]
### --------------------------------
### Mode to avoid noise sharpening & ringing
###
### secure [bool]
### -------------
### Mode to avoid banding & oil painting (or face wax) effect of sharpening
###
### source [clip]
### -------------
### If source is defined, LSFmod doesn't sharp more a denoised clip than this source clip
### In this mode, you can safely set Lmode=0 & PP=off
###    Usage:   denoised.LSFmod(source=source)
###    Example: last.FFT3DFilter().LSFmod(source=last,Lmode=0,soft=0)
###
###
###
### +----------------------+
### | NONLINEAR SHARPENING |
### +----------------------+
###
### Szrp [int]
### ----------
### Zero Point:
###    - differences below Szrp are amplified (overdrive sharpening)
###    - differences above Szrp are reduced   (reduced sharpening)
###
### Spwr [int]
### ----------
### Power: exponent for sharpener
###
### SdmpLo [int]
### ------------
### Damp Low: reduce sharpening for small changes [0:disable]
###
### SdmpHi [int]
### ------------
### Damp High: reduce sharpening for big changes [0:disable]
###
###
###
### +----------+
### | LIMITING |
### +----------+
###
### Lmode [int: ...,0,1,2,3,4]
### --------------------------
### Limit mode:
###    <0 : Limit with repair (ex: Lmode=-1 --> repair(1), Lmode=-5 --> repair(5)...)
###    =0 : No limit
###    =1 : Limit to over/undershoot
###    =2 : Limit to over/undershoot on edges and no limit on not-edges
###    =3 : Limit to zero on edges and to over/undershoot on not-edges
###    =4 : Limit to over/undershoot on edges and to over/undershoot2 on not-edges
###
### overshoot [int]
### ---------------
### Limit for pixels that get brighter during sharpening
###
### undershoot [int]
### ----------------
### Limit for pixels that get darker during sharpening
###
### overshoot2 [int]
### ----------------
### Same as overshoot, only for Lmode=4
###
### undershoot2 [int]
### -----------------
### Same as undershoot, only for Lmode=4
###
###
###
### +-----------------+
### | POST-PROCESSING |
### +-----------------+
###
### soft [int: -2,-1,0...100]
### -------------------------
### Soft the sharpening effect (-1 = old autocalculate, -2 = new autocalculate)
###
### soothe [bool]
### -------------
###    =True  : Enable soothe temporal stabilization
###    =False : Disable soothe temporal stabilization
###
### keep [int: 0...100]
### -------------------
### Minimum percent of the original sharpening to keep (only with soothe=True)
###
###
###
### +-------+
### | EDGES |
### +-------+
###
### edgemode [int: -1,0,1,2]
### ------------------------
###    =-1 : Show edgemask
###    = 0 : Sharpening all
###    = 1 : Sharpening only edges
###    = 2 : Sharpening only not-edges
###
### edgemaskHQ [bool]
### -----------------
###    =True  : Original edgemask
###    =False : Faster edgemask
###
###
###
### +------------+
### | UPSAMPLING |
### +------------+
###
### ss_x ; ss_y [float]
### -------------------
### Supersampling factor (reduce aliasing on edges)
###
### noring [bool]
### -------------
### In case of supersampling, indicates that a non-ringing algorithm must be used
###
### dest_x ; dest_y [int]
### ---------------------
### Output resolution after sharpening (avoid a resizing step)
###
###
###
### +----------+
### | SETTINGS |
### +----------+
###
### defaults [string: "old" or "slow" or "fast"]
### --------------------------------------------
###    = "old"  : Reset settings to original version (output will be THE SAME AS LSF)
###    = "slow" : Enable SLOW modded version settings
###    = "fast" : Enable FAST modded version settings
###  --> /!\ [default:"fast"]
###
###
### defaults="old" :  - strength    = 100
### ----------------  - Smode       = 1
###                   - Smethod     = Smode==1?2:1
###                   - kernel      = 11
###
###                   - preblur     = false
###                   - secure      = false
###                   - source      = undefined
###
###                   - Szrp        = 16
###                   - Spwr        = 2
###                   - SdmpLo      = strength/25
###                   - SdmpHi      = 0
###
###                   - Lmode       = 1
###                   - overshoot   = 1
###                   - undershoot  = overshoot
###                   - overshoot2  = overshoot*2
###                   - undershoot2 = overshoot2
###
###                   - soft        = 0
###                   - soothe      = false
###                   - keep        = 25
###
###                   - edgemode    = 0
###                   - edgemaskHQ  = true
###
###                   - ss_x        = Smode==1?1.50:1.25
###                   - ss_y        = ss_x
###                   - noring      = false
###                   - dest_x      = ox
###                   - dest_y      = oy
###
###
### defaults="slow" : - strength    = 100
### ----------------- - Smode       = 2
###                   - Smethod     = 3
###                   - kernel      = 11
###
###                   - preblur     = false
###                   - secure      = true
###                   - source      = undefined
###
###                   - Szrp        = 16
###                   - Spwr        = 4
###                   - SdmpLo      = 4
###                   - SdmpHi      = 48
###
###                   - Lmode       = 4
###                   - overshoot   = strength/100
###                   - undershoot  = overshoot
###                   - overshoot2  = overshoot*2
###                   - undershoot2 = overshoot2
###
###                   - soft        = -2
###                   - soothe      = true
###                   - keep        = 20
###
###                   - edgemode    = 0
###                   - edgemaskHQ  = true
###
###                   - ss_x        = 1.50
###                   - ss_y        = ss_x
###                   - noring      = false
###                   - dest_x      = ox
###                   - dest_y      = oy
###
###
### defaults="fast" : - strength    = 100
### ----------------- - Smode       = 1
###                   - Smethod     = 2
###                   - kernel      = 11
###
###                   - preblur     = false
###                   - secure      = true
###                   - source      = undefined
###
###                   - Szrp        = 16
###                   - Spwr        = 4
###                   - SdmpLo      = 4
###                   - SdmpHi      = 48
###
###                   - Lmode       = 1
###                   - overshoot   = strength/100
###                   - undershoot  = overshoot
###                   - overshoot2  = overshoot*2
###                   - undershoot2 = overshoot2
###
###                   - soft        = 0
###                   - soothe      = true
###                   - keep        = 20
###
###                   - edgemode    = 0
###                   - edgemaskHQ  = false
###
###                   - ss_x        = 1.25
###                   - ss_y        = ss_x
###                   - noring      = false
###                   - dest_x      = ox
###                   - dest_y      = oy
###
################################################################################################
def LSFmod(input, strength=100, Smode=None, Smethod=None, kernel=11, preblur=False, secure=None, source=None,
           Szrp=16, Spwr=None, SdmpLo=None, SdmpHi=None, Lmode=None, overshoot=None, undershoot=None, overshoot2=None, undershoot2=None,
           soft=None, soothe=None, keep=None, edgemode=0, edgemaskHQ=None, ss_x=None, ss_y=None, noring=False, dest_x=None, dest_y=None, defaults='fast'):
    core = vs.get_core()
    
    if not isinstance(input, vs.VideoNode):
        raise ValueError('LSFmod: This is not a clip !')
    if source is not None and (not isinstance(source, vs.VideoNode) or source.format.id != input.format.id):
        raise ValueError("LSFmod: 'source' must be the same format as input !")
    
    shift = input.format.bits_per_sample - 8
    multiple = 2 ** shift
    median = 128 << shift
    peak = (1 << input.format.bits_per_sample) - 1
    
    ### DEFAULTS
    try:
        num = ['old', 'slow', 'fast'].index(defaults.lower())
    except:
        raise ValueError('LSFmod: Defaults must be "old" or "slow" or "fast" !')
    
    ox = input.width
    oy = input.height
    
    if Smode is None:
        Smode = [1, 2, 1][num]
    if Smethod is None:
        Smethod = [2 if Smode == 1 else 1, 3, 2][num]
    if secure is None:
        secure = [False, True, True][num]
    if Spwr is None:
        Spwr = [2, 4, 4][num]
    if SdmpLo is None:
        SdmpLo = [int(strength / 25), 4, 4][num]
    if SdmpHi is None:
        SdmpHi = [0, 48, 48][num]
    if Lmode is None:
        Lmode = [1, 4, 1][num]
    if overshoot is None:
        overshoot = [1, int(strength / 100), int(strength / 100)][num]
    if undershoot is None:
        undershoot = overshoot
    if overshoot2 is None:
        overshoot2 = overshoot * 2
    if undershoot2 is None:
        undershoot2 = overshoot2
    if soft is None:
        soft = [0, -2, 0][num]
    if soothe is None:
        soothe = [False, True, True][num]
    if keep is None:
        keep = [25, 20, 20][num]
    if edgemaskHQ is None:
        edgemaskHQ = [True, True, False][num]
    if ss_x is None:
        ss_x = [1.5 if Smode == 1 else 1.25, 1.5, 1.25][num]
    if ss_y is None:
        ss_y = ss_x
    if dest_x is None:
        dest_x = ox
    if dest_y is None:
        dest_y = oy
    
    if soft == -1:
        soft = math.sqrt(((ss_x + ss_y) / 2 - 1) * 100) * 10
    elif soft <= -2:
        soft = int((1 + (2 / (ss_x + ss_y))) * math.sqrt(strength))
    soft = min(soft, 100)
    
    xxs = round(ox * ss_x / 8) * 8
    yys = round(oy * ss_y / 8) * 8
    
    Str = strength / 100
    
    # x 128 - y 128 - * 0 < 128 x 128 - abs y 128 - abs < x y ? ?
    def get_lut1(x, y):
        if (x - 128) * (y - 128) < 0:
            return 128
        elif abs(x - 128) < abs(y - 128):
            return x
        else:
            return y
    # x y == x x x y - abs Szrp / 1 Spwr / ^ Szrp * str * x y - x y - abs / * x y - 2 ^ Szrp 2 ^ SdmpLo + * x y - 2 ^ SdmpLo + Szrp 2 ^ * / * 1 SdmpHi 0 == 0 Szrp SdmpHi / 4 ^ ? + 1 SdmpHi 0 == 0 x y - abs SdmpHi / 4 ^ ? + / * + ?
    def get_lut2(x):
        if x == median:
            return x
        else:
            tmp1 = (x - median) / multiple
            tmp2 = tmp1 ** 2
            tmp3 = Szrp ** 2
            return min(max(round(x + (abs(tmp1) / Szrp) ** (1 / Spwr) * Szrp * (Str * multiple) * (1 if x > median else -1) * (tmp2 * (tmp3 + SdmpLo) / ((tmp2 + SdmpLo) * tmp3)) * ((1 + (0 if SdmpHi == 0 else (Szrp / SdmpHi) ** 4)) / (1 + (0 if SdmpHi == 0 else (abs(tmp1) / SdmpHi) ** 4)))), 0), peak)
    # x 128 / 0.86 ^ 255 *
    def get_lut3(x):
        return min(round((x / multiple / 128) ** 0.86 * 255 * multiple), peak)
    # x 32 / 0.86 ^ 255 *
    def get_lut4(x):
        return min(round((x / multiple / 32) ** 0.86 * 255 * multiple), peak)
    # x 128 - abs y 128 - abs > y soft * x (100-soft) * + 100 / x ?
    def get_lut5(x, y):
        if abs(x - 128) > abs(y - 128):
            return round((y * soft + x * (100 - soft)) / 100)
        else:
            return x
    # x 128 - y 128 - * 0 < x 128 - 100 / keep * 128 + x 128 - abs y 128 - abs > x keep * y 100 keep - * + 100 / x ? ?
    def get_lut6(x, y):
        if (x - 128) * (y - 128) < 0:
            return round((x - 128) / 100 * keep + 128)
        elif abs(x - 128) > abs(y - 128):
            return round((x * keep + y * (100 - keep)) / 100)
        else:
            return x
    
    ### SHARP
    if ss_x > 1 or ss_y > 1:
        tmp = Resize(input, xxs, yys, kernel='spline64' if noring else 'spline36', noring=noring)
    else:
        tmp = input
    
    if input.format.num_planes == 3:
        tmp_src = tmp
        tmp = core.std.ShufflePlanes(tmp, planes=[0], colorfamily=vs.GRAY)
    
    if not preblur:
        pre = tmp
    else:
        diff1 = core.std.MakeDiff(tmp, core.rgvs.RemoveGrain(tmp, 11))
        diff2 = core.std.MakeDiff(tmp, core.rgvs.RemoveGrain(tmp, 4))
        if shift > 0:
            clip2 = core.std.Expr([diff1, diff2], ['x {median} - y {median} - * 0 < {median} x {median} - abs y {median} - abs < x y ? ?'.format(median=median)])
        else:
            clip2 = core.std.Lut2(diff1, diff2, function=get_lut1)
        pre = core.std.MakeDiff(tmp, clip2)
    
    dark_limit = core.generic.Minimum(pre)
    bright_limit = core.generic.Maximum(pre)
    minmaxavg = core.std.Merge(dark_limit, bright_limit)
    
    if Smethod <= 1:
        method = core.rgvs.RemoveGrain(pre, kernel)
    elif Smethod == 2:
        method = minmaxavg
    else:
        method = core.rgvs.RemoveGrain(minmaxavg, kernel)
    
    if secure:
        method = core.std.Expr([method, pre], ['x y < x {i} + x y > x {i} - x ? ?'.format(i=1<<shift)])
    
    if preblur:
        method = core.std.MakeDiff(tmp, core.std.MakeDiff(pre, method))
    
    if Smode <= 1:
        normsharp = core.std.Expr([tmp, method], ['x x y - {Str} * +'.format(Str=Str)])
    else:
        sharpdiff = core.std.MakeDiff(tmp, method)
        sharpdiff = core.std.Lut(sharpdiff, function=get_lut2)
        normsharp = core.std.MergeDiff(method, sharpdiff)
    
    ### LIMIT
    normal = Clamp(normsharp, bright_limit, dark_limit, overshoot, undershoot)
    second = Clamp(normsharp, bright_limit, dark_limit, overshoot2, undershoot2)
    zero = Clamp(normsharp, bright_limit, dark_limit, 0, 0)
    
    if edgemaskHQ:
        edge = core.std.Lut(core.std.Expr([core.generic.Convolution(tmp, [8, 16, 8, 0, 0, 0, -8, -16, -8], divisor=4, saturate=False),
                                           core.generic.Convolution(tmp, [8, 0, -8, 16, 0, -16, 8, 0, -8], divisor=4, saturate=False)],
                                          ['x y max']),
                            function=get_lut3)
    else:
        edge = core.std.Lut(core.generic.Sobel(tmp, rshift=2), function=get_lut4)
    
    if Lmode < 0:
        limit1 = core.rgvs.Repair(normsharp, tmp, abs(Lmode))
    elif Lmode == 0:
        limit1 = normsharp
    elif Lmode == 1:
        limit1 = normal
    elif Lmode == 2:
        limit1 = core.std.MaskedMerge(normsharp, normal, core.generic.Inflate(edge))
    elif Lmode == 3:
        limit1 = core.std.MaskedMerge(normal, zero, core.generic.Inflate(edge))
    else:
        limit1 = core.std.MaskedMerge(second, normal, core.generic.Inflate(edge))
    
    if edgemode <= 0:
        limit2 = limit1
    elif edgemode == 1:
        limit2 = core.std.MaskedMerge(tmp, limit1, core.rgvs.RemoveGrain(core.generic.Inflate(core.generic.Inflate(edge)), 11))
    else:
        limit2 = core.std.MaskedMerge(limit1, tmp, core.rgvs.RemoveGrain(core.generic.Inflate(core.generic.Inflate(edge)), 11))
    
    ### SOFT
    if soft == 0:
        PP1 = limit2
    else:
        sharpdiff = core.std.MakeDiff(tmp, limit2)
        sharpdiff2 = core.rgvs.RemoveGrain(sharpdiff, 19)
        if shift > 0:
            sharpdiff3 = core.std.Expr([sharpdiff, sharpdiff2],
                                       ['x {median} - abs y {median} - abs > y {soft} * x {i} * + 100 / x ?'.format(median=median, soft=soft, i=100-soft)])
        else:
            sharpdiff3 = core.std.Lut2(sharpdiff, sharpdiff2, function=get_lut5)
        PP1 = core.std.MakeDiff(tmp, sharpdiff3)
    
    ### SOOTHE
    if soothe:
        diff = core.std.MakeDiff(tmp, PP1)
        diff2 = TemporalSoften(diff, 1, 255<<shift, 0, 32<<shift, 2)
        if shift > 0:
            diff3 = core.std.Expr([diff, diff2], ['x {median} - y {median} - * 0 < x {median} - 100 / {keep} * {median} + x {median} - abs y {median} - abs > x {keep} * y 100 {keep} - * + 100 / x ? ?'.format(median=median, keep=keep)])
        else:
            diff3 = core.std.Lut2(diff, diff2, function=get_lut6)
        PP2 = core.std.MakeDiff(tmp, diff3)
    else:
        PP2 = PP1
    
    ### OUTPUT
    if dest_x != ox or dest_y != oy:
        if input.format.num_planes == 3:
            PP2 = core.std.ShufflePlanes([PP2, tmp_src], planes=[0, 1, 2], colorfamily=input.format.color_family)
        out = Resize(PP2, dest_x, dest_y)
    elif ss_x > 1 or ss_y > 1:
        out = Resize(PP2, dest_x, dest_y)
        if input.format.num_planes == 3:
            out = core.std.ShufflePlanes([out, input], planes=[0, 1, 2], colorfamily=input.format.color_family)
    elif input.format.num_planes == 3:
        out = core.std.ShufflePlanes([PP2, input], planes=[0, 1, 2], colorfamily=input.format.color_family)
    else:
        out = PP2
    
    if edgemode <= -1:
        return Resize(edge, dest_x, dest_y)
    elif source is not None:
        if dest_x != ox or dest_y != oy:
            src = Resize(source, dest_x, dest_y)
            In = Resize(input, dest_x, dest_y)
        else:
            src = source
            In = input
        
        shrpD = core.std.MakeDiff(In, out, planes=[0])
        expr = 'x {median} - abs y {median} - abs < x y ?'.format(median=median)
        shrpL = core.std.Expr([core.rgvs.Repair(shrpD, core.std.MakeDiff(In, src, planes=[0]), [1] if input.format.num_planes==1 else [1, 0]), shrpD],
                              [expr] if input.format.num_planes==1 else [expr, ''])
        return core.std.MakeDiff(In, shrpL, planes=[0])
    else:
        return out


# Parameters:
#  g1str [float]       - [0.0 - ???] strength of grain / for dark areas. Default is 7.0
#  g2str [float]       - [0.0 - ???] strength of grain / for midtone areas. Default is 5.0
#  g3str [float]       - [0.0 - ???] strength of grain / for bright areas. Default is 3.0
#  g1shrp [int]        - [0 - 100] sharpness of grain / for dark areas (NO EFFECT when g1size=1.0 !!). Default is 60
#  g2shrp [int]        - [0 - 100] sharpness of grain / for midtone areas (NO EFFECT when g2size=1.0 !!). Default is 66
#  g3shrp [int]        - [0 - 100] sharpness of grain / for bright areas (NO EFFECT when g3size=1.0 !!). Default is 80
#  g1size [float]      - [0.5 - 4.0] size of grain / for dark areas. Default is 1.5
#  g2size [float]      - [0.5 - 4.0] size of grain / for midtone areas. Default is 1.2
#  g3size [float]      - [0.5 - 4.0] size of grain / for bright areas. Default is 0.9
#  temp_avg [int]      - [0 - 100] percentage of noise's temporal averaging. Default is 0
#  ontop_grain [float] - [0 - ???] additional grain to put on top of prev. generated grain. Default is 0.0
#  th1 [int]           - start of dark->midtone mixing zone. Default is 24
#  th2 [int]           - end of dark->midtone mixing zone. Default is 56
#  th3 [int]           - start of midtone->bright mixing zone. Default is 128
#  th4 [int]           - end of midtone->bright mixing zone. Default is 160
def GrainFactory3(clp, g1str=7., g2str=5., g3str=3., g1shrp=60, g2shrp=66, g3shrp=80, g1size=1.5, g2size=1.2, g3size=0.9, temp_avg=0, ontop_grain=0.,
                  th1=24, th2=56, th3=128, th4=160):
    core = vs.get_core()
    
    if not isinstance(clp, vs.VideoNode):
        raise ValueError('GrainFactory3: This is not a clip !')
    
    shift = clp.format.bits_per_sample - 8
    peak = (1 << clp.format.bits_per_sample) - 1
    
    ox = clp.width
    oy = clp.height
    sx1 = m4(ox / g1size)
    sy1 = m4(oy / g1size)
    sx1a = m4((ox + sx1) / 2)
    sy1a = m4((oy + sy1) / 2)
    sx2 = m4(ox / g2size)
    sy2 = m4(oy / g2size)
    sx2a = m4((ox + sx2) / 2)
    sy2a = m4((oy + sy2) / 2)
    sx3 = m4(ox / g3size)
    sy3 = m4(oy / g3size)
    sx3a = m4((ox + sx3) / 2)
    sy3a = m4((oy + sy3) / 2)
    
    b1 = g1shrp / -50 + 1
    b2 = g2shrp / -50 + 1
    b3 = g3shrp / -50 + 1
    b1a = b1 / 2
    b2a = b2 / 2
    b3a = b3 / 2
    c1 = (1 - b1) / 2
    c2 = (1 - b2) / 2
    c3 = (1 - b3) / 2
    c1a = (1 - b1a) / 2
    c2a = (1 - b2a) / 2
    c3a = (1 - b3a) / 2
    tmpavg = temp_avg / 100
    th1 <<= shift
    th2 <<= shift
    th3 <<= shift
    th4 <<= shift
    
    if clp.format.num_planes == 3:
        clp_src = clp
        clp = core.std.ShufflePlanes(clp, planes=[0], colorfamily=vs.GRAY)
    else:
        clp_src = None
    
    grainlayer1 = core.grain.Add(core.std.BlankClip(clp, width=sx1, height=sy1, color=128<<shift), g1str)
    if g1size != 1 and (sx1 != ox or sy1 != oy):
        if g1size > 1.5:
            grainlayer1 = Resize(core.fmtc.resample(grainlayer1, sx1a, sy1a, kernel='bicubic', a1=b1a, a2=c1a),
                                 ox, oy, kernel='bicubic', a1=b1a, a2=c1a, bits=clp.format.bits_per_sample)
        else:
            grainlayer1 = Resize(grainlayer1, ox, oy, kernel='bicubic', a1=b1, a2=c1)
    
    grainlayer2 = core.grain.Add(core.std.BlankClip(clp, width=sx2, height=sy2, color=128<<shift), g2str)
    if g2size != 1 and (sx2 != ox or sy2 != oy):
        if g2size > 1.5:
            grainlayer2 = Resize(core.fmtc.resample(grainlayer2, sx2a, sy2a, kernel='bicubic', a1=b2a, a2=c2a),
                                 ox, oy, kernel='bicubic', a1=b2a, a2=c2a, bits=clp.format.bits_per_sample)
        else:
            grainlayer2 = Resize(grainlayer2, ox, oy, kernel='bicubic', a1=b2, a2=c2)
    
    grainlayer3 = core.grain.Add(core.std.BlankClip(clp, width=sx3, height=sy3, color=128<<shift), g3str)
    if g3size != 1 and (sx3 != ox or sy3 != oy):
        if g3size > 1.5:
            grainlayer3 = Resize(core.fmtc.resample(grainlayer3, sx3a, sy3a, kernel='bicubic', a1=b3a, a2=c3a),
                                 ox, oy, kernel='bicubic', a1=b3a, a2=c3a, bits=clp.format.bits_per_sample)
        else:
            grainlayer3 = Resize(grainlayer3, ox, oy, kernel='bicubic', a1=b3, a2=c3)
    
    # x th1 < 0 x th2 > 255 255 th2 th1 - / x th1 - * ? ?
    def get_lut1(x):
        if x < th1:
            return 0
        elif x > th2:
            return peak
        else:
            return min(max(round(peak / (th2 - th1) * (x - th1)), 0), peak)
    # x th3 < 0 x th4 > 255 255 th4 th3 - / x th3 - * ? ?
    def get_lut2(x):
        if x < th3:
            return 0
        elif x > th4:
            return peak
        else:
            return min(max(round(peak / (th4 - th3) * (x - th3)), 0), peak)
    
    grainlayer = core.std.MaskedMerge(core.std.MaskedMerge(grainlayer1, grainlayer2, core.std.Lut(clp, function=get_lut1)), grainlayer3,
                                      core.std.Lut(clp, function=get_lut2))
    if temp_avg > 0:
        grainlayer = core.std.Merge(grainlayer, TemporalSoften(grainlayer, 1, 255<<shift, 0, 0, 2), weight=[tmpavg])
    if ontop_grain > 0:
        grainlayer = core.grain.Add(grainlayer, ontop_grain)
    result = core.std.MakeDiff(clp, grainlayer)
    
    if clp_src is not None:
        return core.std.ShufflePlanes([result, clp_src], planes=[0, 1, 2], colorfamily=clp_src.format.color_family)
    else:
        return result


####################
#                  #
# HELPER FUNCTIONS #
#                  #
####################
def Clamp(clip, bright_limit, dark_limit, overshoot=0, undershoot=0, planes=[0, 1, 2]):
    core = vs.get_core()
    
    if clip.format.id != bright_limit.format.id or clip.format.id != dark_limit.format.id:
        raise ValueError('Clamp: clips must have the same format !')
    if isinstance(planes, int):
        planes = [planes]
    
    bright_expr = 'x y {overshoot} + > y {overshoot} + x ?'.format(overshoot=overshoot)
    dark_expr = 'x y {undershoot} - < y {undershoot} - x ?'.format(undershoot=undershoot)
    if clip.format.num_planes == 3:
        bright_expr = [bright_expr if 0 in planes else '', bright_expr if 1 in planes else '', bright_expr if 2 in planes else '']
        dark_expr = [dark_expr if 0 in planes else '', dark_expr if 1 in planes else '', dark_expr if 2 in planes else '']
    
    clip = core.std.Expr([clip, bright_limit], bright_expr)
    return core.std.Expr([clip, dark_limit], dark_expr)

def LimitDiff(filtered, original, smooth=True, thr=1., elast=None, darkthr=None, planes=[0, 1, 2]):
    core = vs.get_core()
    
    if filtered.format.id != original.format.id:
        raise ValueError('LimitDiff: clips must have the same format !')
    
    shift = filtered.format.bits_per_sample - 8
    median = 128 << shift
    
    if elast is None:
        elast = 3. if smooth else 128 / thr
    if darkthr is None:
        darkthr = thr
    
    if filtered.format.num_planes == 1:
        planes = [0]
    if isinstance(planes, int):
        planes = [planes]
    
    if thr <= 0 and darkthr <= 0:
        return original
    elif thr >= 128 and darkthr >= 128:
        return filtered
    elast = max(elast, 1.)
    if elast == 1:
        smooth = False
    thr *= 2 ** shift
    darkthr *= 2 ** shift
    
    # diff   = filtered - original
    # alpha  = 1 / (thr * (elast - 1))
    # beta   = thr * elast
    # When smooth=True  :
    # output = diff <= thr  ? filtered : \
    #          diff >= beta ? original : \
    #                         original + alpha * diff * (beta - abs(diff))
    # When smooth=False :
    # output = diff <= thr  ? filtered : \
    #          diff >= beta ? original : \
    #                         original + thr * (diff / abs(diff))
    def get_lut1(x):
        _diff = x - median
        _absdiff = abs(_diff)
        _thr = darkthr if _diff > 0 else thr
        _beta = _thr * elast
        _smooth = (1 / (_thr * (elast - 1))) * _diff * (_beta - _absdiff) if smooth else _thr * (_diff / _absdiff)
        if _absdiff <= _thr:
            return x
        elif _absdiff >= _beta:
            return median
        else:
            return round(median + _smooth)
    def get_lut2(x):
        _diff = x - median
        _absdiff = abs(_diff)
        _beta = thr * elast
        _smooth = (1 / (thr * (elast - 1))) * _diff * (_beta - _absdiff) if smooth else thr * (_diff / _absdiff)
        if _absdiff <= thr:
            return x
        elif _absdiff >= _beta:
            return median
        else:
            return round(median + _smooth)
    
    diff = core.std.MakeDiff(filtered, original, planes=planes)
    if 0 in planes:
        diff = core.std.Lut(diff, planes=[0], function=get_lut1)
    if 1 in planes or 2 in planes:
        diff = core.std.Lut(diff, planes=[1, 2] if 1 in planes and 2 in planes else [1] if 1 in planes else [2], function=get_lut2)
    return core.std.MergeDiff(original, diff, planes=planes)

def Bob(clip, b=1/3, c=1/3, tff=None):
    core = vs.get_core()
    
    if not isinstance(tff, bool):
        raise ValueError("Bob: 'tff' must be set. Setting tff to true means top field first and false means bottom field first")
    
    bits = clip.format.bits_per_sample
    
    clip = core.std.SeparateFields(clip, tff)
    clip = core.fmtc.resample(clip, scalev=2, kernel='bicubic', a1=b, a2=c, interlaced=1, interlacedd=0, tff=tff)
    
    if bits < 16:
        return core.fmtc.bitdepth(clip, bits=bits)
    else:
        return clip

def TemporalSoften(clip, radius=4, luma_threshold=4, chroma_threshold=8, scenechange=15, mode=2):
    core = vs.get_core()
    
    if scenechange:
        clip = set_scenechange(clip, scenechange)
    return core.focus2.TemporalSoften2(clip, radius, luma_threshold, chroma_threshold, scenechange)

def Weave(clip, tff):
    core = vs.get_core()
    return core.std.SelectEvery(core.std.DoubleWeave(clip, tff), 2, [0])

def m4(x):
    return 16 if x < 16 else int(round(x / 4) * 4)

def set_scenechange(clip, thresh=15):
    core = vs.get_core()
    
    def set_props(n, f):
        fout = f[0].copy()
        fout.props._SceneChangePrev = f[1].props._SceneChangePrev
        fout.props._SceneChangeNext = f[1].props._SceneChangeNext
        return fout
    
    sc = clip
    if clip.format.color_family == vs.RGB:
        sc = core.std.ShufflePlanes(clip, planes=[0], colorfamily=vs.GRAY)
    sc = core.scd.Detect(sc, thresh)
    if clip.format.color_family == vs.RGB:
        sc = core.std.ModifyFrame(clip, clips=[clip, sc], selector=set_props)
    return sc

########################################
## Didée's functions:
#
# contra-sharpening: sharpen the denoised clip, but don't add more to any pixel than what was removed previously.
# script function from Didée, at the VERY GRAINY thread (http://forum.doom9.org/showthread.php?p=1076491#post1076491)
def ContraSharpening(denoised, original):
    core = vs.get_core()
    
    if denoised.format.id != original.format.id:
        raise ValueError('ContraSharpening: clips must have the same format !')
    
    s = MinBlur(denoised, 1, planes=[0])                                                                                    # Damp down remaining spots of the denoised clip.
    allD = core.std.MakeDiff(original, denoised, planes=[0])                                                                # The difference achieved by the denoising.
    ssD = core.std.MakeDiff(s, core.rgvs.RemoveGrain(s, [11] if denoised.format.num_planes==1 else [11, 0]), planes=[0])    # The difference of a simple kernel blur.
    ssDD = core.rgvs.Repair(ssD, allD, [1] if denoised.format.num_planes==1 else [1, 0])                                    # Limit the difference to the max of what the denoising removed locally.
    expr = 'x {median} - abs y {median} - abs < x y ?'.format(median=1<<(denoised.format.bits_per_sample-1))
    ssDD = core.std.Expr([ssDD, ssD], [expr] if denoised.format.num_planes==1 else [expr, ''])                              # abs(diff) after limiting may not be bigger than before.
    return core.std.MergeDiff(denoised, ssDD, planes=[0])                                                                   # Apply the limited difference. (Sharpening is just inverse blurring)

# MinBlur   by Didée (http://avisynth.org/mediawiki/MinBlur)
# Nifty Gauss/Median combination
def MinBlur(clp, r=1, planes=[0, 1, 2]):
    core = vs.get_core()
    
    if clp.format.num_planes == 1:
        planes = [0]
    if isinstance(planes, int):
        planes = [planes]
    
    expr = 'x {median} - y {median} - * 0 < {median} x {median} - abs y {median} - abs < x y ? ?'.format(median=1<<(clp.format.bits_per_sample-1))
    if 0 in planes:
        Y4 = 4
        Y11 = 11
        Y20 = 20
        Yexpr = expr
    else:
        Y4 = Y11 = Y20 = 0
        Yexpr = ''
    if 1 in planes:
        U4 = 4
        U11 = 11
        U20 = 20
        Uexpr = expr
    else:
        U4 = U11 = U20 = 0
        Uexpr = ''
    if 2 in planes:
        V4 = 4
        V11 = 11
        V20 = 20
        Vexpr = expr
    else:
        V4 = V11 = V20 = 0
        Vexpr = ''
    M4 = [Y4] if clp.format.num_planes == 1 else [Y4, U4, V4]
    M11 = [Y11] if clp.format.num_planes == 1 else [Y11, U11, V11]
    M20 = [Y20] if clp.format.num_planes == 1 else [Y20, U20, V20]
    
    # x 128 - y 128 - * 0 < 128 x 128 - abs y 128 - abs < x y ? ?
    def get_lut(x, y):
        if (x - 128) * (y - 128) < 0:
            return 128
        elif abs(x - 128) < abs(y - 128):
            return x
        else:
            return y
    
    if r <= 0:
        RG11 = sbr(clp, planes=planes)
        RG4 = core.rgvs.RemoveGrain(clp, M4)
    elif r == 1:
        RG11 = core.rgvs.RemoveGrain(clp, M11)
        RG4 = core.rgvs.RemoveGrain(clp, M4)
    elif r == 2:
        RG11 = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(clp, M11), M20)
        RG4 = core.ctmf.CTMF(clp, radius=2, planes=planes)
    else:
        RG11 = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(clp, M11), M20), M20)
        RG4 = core.ctmf.CTMF(clp, radius=3, planes=planes)
    RG11D = core.std.MakeDiff(clp, RG11, planes=planes)
    RG4D = core.std.MakeDiff(clp, RG4, planes=planes)
    if clp.format.bits_per_sample > 8:
        DD = core.std.Expr([RG11D, RG4D], [Yexpr] if clp.format.num_planes==1 else [Yexpr, Uexpr, Vexpr])
    else:
        DD = core.std.Lut2(RG11D, RG4D, planes=planes, function=get_lut)
    return core.std.MakeDiff(clp, DD, planes=planes)

# make a highpass on a blur's difference (http://forum.doom9.org/showthread.php?p=1323257#post1323257)
def sbr(clp, r=1, planes=[0, 1, 2]):
    core = vs.get_core()
    
    if clp.format.num_planes == 1:
        planes = [0]
    if isinstance(planes, int):
        planes = [planes]
    
    expr = 'x y - x {median} - * 0 < {median} x y - abs x {median} - abs < x y - {median} + x ? ?'.format(median=1<<(clp.format.bits_per_sample-1))
    if 0 in planes:
        Y11 = 11
        Y20 = 20
        Yexpr = expr
    else:
        Y11 = Y20 = 0
        Yexpr = ''
    if 1 in planes:
        U11 = 11
        U20 = 20
        Uexpr = expr
    else:
        U11 = U20 = 0
        Uexpr = ''
    if 2 in planes:
        V11 = 11
        V20 = 20
        Vexpr = expr
    else:
        V11 = V20 = 0
        Vexpr = ''
    M11 = [Y11] if clp.format.num_planes == 1 else [Y11, U11, V11]
    M20 = [Y20] if clp.format.num_planes == 1 else [Y20, U20, V20]
    
    # x y - x 128 - * 0 < 128 x y - abs x 128 - abs < x y - 128 + x ? ?
    def get_lut(x, y):
        if (x - y) * (x - 128) < 0:
            return 128
        elif abs(x - y) < abs(x - 128):
            return x - y + 128
        else:
            return x
    
    if r <= 1:
        RG11 = core.rgvs.RemoveGrain(clp, M11)
    elif r == 2:
        RG11 = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(clp, M11), M20)
    else:
        RG11 = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(clp, M11), M20), M20)
    RG11D = core.std.MakeDiff(clp, RG11, planes=planes)
    if r <= 1:
        RG11DS = core.rgvs.RemoveGrain(RG11D, M11)
    elif r == 2:
        RG11DS = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(RG11D, M11), M20)
    else:
        RG11DS = core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(core.rgvs.RemoveGrain(RG11D, M11), M20), M20)
    if clp.format.bits_per_sample > 8:
        RG11DD = core.std.Expr([RG11D, RG11DS], [Yexpr] if clp.format.num_planes==1 else [Yexpr, Uexpr, Vexpr])
    else:
        RG11DD = core.std.Lut2(RG11D, RG11DS, planes=planes, function=get_lut)
    return core.std.MakeDiff(clp, RG11DD, planes=planes)

def sbrV(clp, r=1, planes=[0, 1, 2]):
    core = vs.get_core()
    
    if clp.format.num_planes == 1:
        planes = [0]
    if isinstance(planes, int):
        planes = [planes]
    
    expr = 'x y - x {median} - * 0 < {median} x y - abs x {median} - abs < x y - {median} + x ? ?'.format(median=1<<(clp.format.bits_per_sample-1))
    Yexpr = expr if 0 in planes else ''
    Uexpr = expr if 1 in planes else ''
    Vexpr = expr if 2 in planes else ''
    
    # x y - x 128 - * 0 < 128 x y - abs x 128 - abs < x y - 128 + x ? ?
    def get_lut(x, y):
        if (x - y) * (x - 128) < 0:
            return 128
        elif abs(x - y) < abs(x - 128):
            return x - y + 128
        else:
            return x
    
    if r <= 1:
        RG11 = core.generic.Convolution(clp, [1, 2, 1], mode='v', planes=planes)
    elif r == 2:
        RG11 = core.generic.Convolution(core.generic.Convolution(clp, [1, 2, 1], mode='v', planes=planes), [1, 4, 6, 4, 1], mode='v', planes=planes)
    else:
        RG11 = core.generic.Convolution(core.generic.Convolution(core.generic.Convolution(clp, [1, 2, 1], mode='v', planes=planes),
                                                                 [1, 4, 6, 4, 1], mode='v', planes=planes), [1, 4, 6, 4, 1], mode='v', planes=planes)
    RG11D = core.std.MakeDiff(clp, RG11, planes=planes)
    if r <= 1:
        RG11DS = core.generic.Convolution(RG11D, [1, 2, 1], mode='v', planes=planes)
    elif r == 2:
        RG11DS = core.generic.Convolution(core.generic.Convolution(RG11D, [1, 2, 1], mode='v', planes=planes), [1, 4, 6, 4, 1], mode='v', planes=planes)
    else:
        RG11DS = core.generic.Convolution(core.generic.Convolution(core.generic.Convolution(RG11D, [1, 2, 1], mode='v', planes=planes),
                                                                   [1, 4, 6, 4, 1], mode='v', planes=planes), [1, 4, 6, 4, 1], mode='v', planes=planes)
    if clp.format.bits_per_sample > 8:
        RG11DD = core.std.Expr([RG11D, RG11DS], [Yexpr] if clp.format.num_planes==1 else [Yexpr, Uexpr, Vexpr])
    else:
        RG11DD = core.std.Lut2(RG11D, RG11DS, planes=planes, function=get_lut)
    return core.std.MakeDiff(clp, RG11DD, planes=planes)

########################################
## cretindesalpes' functions:
#
# Converts luma (and chroma) to PC levels, and optionally allows tweaking for pumping up the darks. (for the clip to be fed to motion search only)
# By courtesy of cretindesalpes. (http://forum.doom9.org/showthread.php?p=1548318#post1548318)
def Dither_Luma_Rebuild(src, s0=2., c=0.0625, chroma=True):
    core = vs.get_core()
    
    shift = src.format.bits_per_sample - 8
    
    def get_lut(x):
        tmp1 = 16 << shift
        tmp2 = 219 << shift
        tmp3 = 256 << shift
        k = (s0 - 1) * c
        t = min(max((x - tmp1) / tmp2, 0), 1)
        return min(round((k * (1 + c - (1 + c) * c / (t + c)) + t * (1 - k)) * tmp3), (1 << src.format.bits_per_sample) - 1)
    
    last = core.std.Lut(src, planes=[0], function=get_lut)
    if chroma and src.format.num_planes == 3:
        return core.std.Expr(last, ['', 'x {median} - 128 * 112 / {median} +'.format(median=128<<shift)])
    else:
        return last

#=============================================================================
#	mt_expand_multi
#	mt_inpand_multi
#
#	Calls mt_expand or mt_inpand multiple times in order to grow or shrink
#	the mask from the desired width and height.
#
#	Parameters:
#	- sw   : Growing/shrinking shape width. 0 is allowed. Default: 1
#	- sh   : Growing/shrinking shape height. 0 is allowed. Default: 1
#	- mode : "rectangle" (default), "ellipse" or "losange". Replaces the
#		mt_xxpand mode. Ellipses are actually combinations of
#		rectangles and losanges and look more like octogons.
#		Losanges are truncated (not scaled) when sw and sh are not
#		equal.
#	Other parameters are the same as mt_xxpand.
#=============================================================================
def mt_expand_multi(src, mode='rectangle', planes=[0, 1, 2], sw=1, sh=1):
    core = vs.get_core()
    
    if src.format.num_planes == 1:
        planes = [0]
    
    if sw > 0 and sh > 0:
        mode_m = [0, 1, 0, 1, 1, 0, 1, 0] if mode == 'losange' or (mode == 'ellipse' and (sw % 3) != 1) else [1, 1, 1, 1, 1, 1, 1, 1]
    elif sw > 0:
        mode_m = [0, 0, 0, 1, 1, 0, 0, 0]
    elif sh > 0:
        mode_m = [0, 1, 0, 0, 0, 0, 1, 0]
    else:
        mode_m = None
    
    if mode_m:
        return mt_expand_multi(core.generic.Maximum(src, planes=planes, coordinates=mode_m), mode=mode, planes=planes, sw=sw-1, sh=sh-1)
    else:
        return src

def mt_inpand_multi(src, mode='rectangle', planes=[0, 1, 2], sw=1, sh=1):
    core = vs.get_core()
    
    if src.format.num_planes == 1:
        planes = [0]
    
    if sw > 0 and sh > 0:
        mode_m = [0, 1, 0, 1, 1, 0, 1, 0] if mode == 'losange' or (mode == 'ellipse' and (sw % 3) != 1) else [1, 1, 1, 1, 1, 1, 1, 1]
    elif sw > 0:
        mode_m = [0, 0, 0, 1, 1, 0, 0, 0]
    elif sh > 0:
        mode_m = [0, 1, 0, 0, 0, 0, 1, 0]
    else:
        mode_m = None
    
    if mode_m:
        return mt_inpand_multi(core.generic.Minimum(src, planes=planes, coordinates=mode_m), mode=mode, planes=planes, sw=sw-1, sh=sh-1)
    else:
        return src

def mt_inflate_multi(src, planes=[0, 1, 2], radius=1):
    core = vs.get_core()
    
    if src.format.num_planes == 1:
        planes = [0]
    
    if radius > 0:
        return mt_inflate_multi(core.generic.Inflate(src, planes=planes), planes=planes, radius=radius-1)
    else:
        return src

def mt_deflate_multi(src, planes=[0, 1, 2], radius=1):
    core = vs.get_core()
    
    if src.format.num_planes == 1:
        planes = [0]
    
    if radius > 0:
        return mt_deflate_multi(core.generic.Deflate(src, planes=planes), planes=planes, radius=radius-1)
    else:
        return src
