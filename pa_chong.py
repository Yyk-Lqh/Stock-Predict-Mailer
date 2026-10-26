import  requests
from lxml import html
import csv

#https://www.moji.com/
#https://www.tiobe.com/tiobe-index/
all_movies = []

def Save_all_movies(all_movies):
    with open('all_movies.csv', 'w', newline='', encoding='utf-8') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames=['名字', '介绍'])
        writer.writeheader()
        writer.writerows(all_movies)
        print("finish")



def get_movie_list(mission_url):
   response2=requests.get(mission_url, timeout=60)
   response2.encoding='utf-8'
   doc2=html.fromstring(response2.text)
   text = doc2.xpath('//html/body/main/section/div/div/article/h1/text()')
   text2=doc2.xpath('//html/body/main/section/div/div/article/p[2]/text()')
   movie_info={
       '名字':text[0].strip() if text else ' ',
       '介绍':text2[0].strip() if text2 else ' '
   }
   print(text)
   print(text2)
   all_movies.append(movie_info)



def main():

   for i in range(1, 2):
        if i == 1:
           target_url = "https://themoviesdb.org/en/movies/?"

        else:
           target_url = f"https://themoviesdb.org/en/movies/?page={i}"

        response = requests.get(target_url, timeout=60)
        response.encoding = 'utf-8'


        doc = html.fromstring(response.text)
        mission = doc.xpath('//html/body/main/section/div/div/div/article/a/@href')

        for i in mission:
            mission_url = "https://themoviesdb.org" + i
            print(mission_url)
            get_movie_list(mission_url)

main()
Save_all_movies(all_movies)












