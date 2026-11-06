import {describe, expect, it, vi} from 'vitest';
import {api} from './api';

describe('public API seam',()=>{
  it('posts a run with the shared camelCase settings contract',async()=>{
    const fetchMock=vi.spyOn(globalThis,'fetch').mockResolvedValue(new Response(JSON.stringify({state:'running',runId:'r-1',videoId:'v-1',stage:'features'}),{status:202}));
    await api.start('v-1',{sampleHz:5,maxImageSize:640,maxFeatures:1500,threads:2,overlap:5});
    const [,init]=fetchMock.mock.calls[0];
    expect(fetchMock.mock.calls[0][0]).toBe('/api/runs');
    expect(JSON.parse(String(init?.body))).toEqual({videoId:'v-1',settings:{sampleHz:5,maxImageSize:640,maxFeatures:1500,threads:2,overlap:5}});
    fetchMock.mockRestore();
  });
});
